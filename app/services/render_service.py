import os
import subprocess
from pathlib import Path
import pysrt
from app.core.errors import RenderError
from app.utils.logger import get_logger

logger = get_logger("RenderService")

class RenderService:
    _cached_encoder = None

    def _test_encoder_works(self, encoder: str) -> bool:
        """Runs a short test command to verify if the encoder can actually initialize and encode."""
        try:
            cmd = [
                "ffmpeg", "-y", "-nostdin",
                "-f", "lavfi", "-i", "color=c=black:s=16x16:d=0.1",
                "-c:v", encoder,
                "-f", "null", "-"
            ]
            subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
            return True
        except Exception:
            return False

    def _detect_best_encoder(self) -> str:
        """Detects and caches the fastest H.264 encoder available in FFmpeg."""
        if RenderService._cached_encoder is not None:
            return RenderService._cached_encoder
            
        try:
            cmd = ["ffmpeg", "-encoders"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            encoders = result.stdout
            
            if "h264_nvenc" in encoders and self._test_encoder_works("h264_nvenc"):
                logger.info("Hardware acceleration detected: Using NVIDIA h264_nvenc encoder.")
                RenderService._cached_encoder = "h264_nvenc"
            elif "h264_qsv" in encoders and self._test_encoder_works("h264_qsv"):
                logger.info("Hardware acceleration detected: Using Intel h264_qsv encoder.")
                RenderService._cached_encoder = "h264_qsv"
            elif "h264_amf" in encoders and self._test_encoder_works("h264_amf"):
                logger.info("Hardware acceleration detected: Using AMD h264_amf encoder.")
                RenderService._cached_encoder = "h264_amf"
            elif "h264_mf" in encoders and self._test_encoder_works("h264_mf"):
                logger.info("Hardware acceleration detected: Using h264_mf encoder.")
                RenderService._cached_encoder = "h264_mf"
            else:
                logger.info("No hardware acceleration encoder working. Using default CPU libx264.")
                RenderService._cached_encoder = "libx264"
        except Exception as e:
            logger.warning(f"Failed to detect hardware encoders: {e}. Falling back to libx264.")
            RenderService._cached_encoder = "libx264"
            
        return RenderService._cached_encoder

    def _escape_windows_path(self, path: Path) -> str:
        """Escapes Windows paths for use within FFmpeg filter arguments (like subtitles)."""
        try:
            # Try to get relative path from current working directory to avoid Windows drive letters/colons
            rel_path = os.path.relpath(path, start=os.getcwd())
            p_str = str(rel_path).replace("\\", "/")
            if ":" not in p_str:
                return p_str
        except Exception as e:
            logger.warning(f"Could not compute relative path for escaping: {e}")
            
        p_str = str(path.resolve()).replace("\\", "/")
        if ":" in p_str:
            drive, rest = p_str.split(":", 1)
            p_str = f"{drive}\\\\\\:{rest}"
        return p_str

    def _wrap_subtitle_text(self, text: str, max_chars: int) -> str:
        words = " ".join(text.replace("\n", " ").split()).split(" ")
        if not words:
            return ""
        lines = ["", ""]
        line_idx = 0
        for word in words:
            candidate = word if not lines[line_idx] else f"{lines[line_idx]} {word}"
            if len(candidate) <= max_chars or not lines[line_idx]:
                lines[line_idx] = candidate
            elif line_idx == 0:
                line_idx = 1
                lines[line_idx] = word
            else:
                lines[line_idx] = f"{lines[line_idx]} {word}".strip()
        return "\\N".join(line for line in lines if line)

    def _ass_alpha_black(self, opacity: float) -> str:
        opacity = max(0.0, min(1.0, opacity))
        alpha = int(round((1.0 - opacity) * 255))
        return f"&H{alpha:02X}000000"

    def _normalize_layout_keys(self, layout: dict) -> dict:
        if not layout:
            return {}
        normalized = {}
        for k, v in layout.items():
            if k in ["x", "subtitle_x_percent"]:
                normalized["x"] = v
            elif k in ["y", "subtitle_y_percent"]:
                normalized["y"] = v
            elif k in ["width", "subtitle_width_percent"]:
                normalized["width"] = v
            elif k in ["height", "subtitle_height_percent"]:
                normalized["height"] = v
            else:
                normalized[k] = v
        return normalized

    def _convert_srt_to_ass(
        self,
        srt_path: Path,
        ass_path: Path,
        subtitle_layout: dict,
        bg_opacity: float,
        stroke_size: int = 3,
        play_w: int = 1080,
        play_h: int = 1920,
        subtitle_style: str = "default",
        mask_subtitle: bool = False,
    ):
        """Converts SRT to ASS using a user-selected normalized subtitle box and style."""
        layout = self._normalize_layout_keys(subtitle_layout)
        subs = pysrt.open(str(srt_path), encoding="utf-8")
        
        # 1. Split long subtitle segments into shorter ones (max 35 chars) with proportional timestamps
        import copy
        new_subs = []
        max_chars = 35
        for sub in subs:
            text = sub.text.strip()
            if len(text) <= max_chars:
                new_subs.append(sub)
                continue
                
            words = text.split()
            chunks = []
            current_chunk = []
            current_length = 0
            for word in words:
                if current_length + len(word) + 1 > max_chars and current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = [word]
                    current_length = len(word)
                else:
                    current_chunk.append(word)
                    current_length += len(word) + 1
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                
            start_ms = sub.start.ordinal
            end_ms = sub.end.ordinal
            duration_ms = end_ms - start_ms
            
            current_time_ms = start_ms
            total_chunk_len = sum(len(c) for c in chunks)
            if total_chunk_len == 0:
                total_chunk_len = 1
                
            for i, chunk in enumerate(chunks):
                chunk_ratio = len(chunk) / total_chunk_len
                chunk_duration_ms = duration_ms * chunk_ratio
                
                chunk_start_ms = int(current_time_ms)
                chunk_end_ms = int(current_time_ms + chunk_duration_ms)
                if i == len(chunks) - 1:
                    chunk_end_ms = end_ms
                    
                new_sub = copy.deepcopy(sub)
                new_sub.text = chunk
                new_sub.start.ordinal = chunk_start_ms
                new_sub.end.ordinal = chunk_end_ms
                new_subs.append(new_sub)
                
                current_time_ms = chunk_end_ms

        # 2. Extend end times to fill small gaps (timeline optimization)
        # Skip this for karaoke and word_highlight styles to prevent subtitle lagging behind voiceover
        if subtitle_style not in ("karaoke", "word_highlight"):
            for i in range(len(new_subs)):
                start = new_subs[i].start.ordinal
                end = new_subs[i].end.ordinal
                if i < len(new_subs) - 1:
                    next_start = new_subs[i+1].start.ordinal
                    gap = next_start - end
                    if gap > 0:
                        if gap < 2000:  # gap < 2s
                            new_subs[i].end.ordinal = next_start - 1
                        else:
                            new_subs[i].end.ordinal = end + 1500
                else:
                    new_subs[i].end.ordinal = end + 1500

        def ms_to_ass_time(ms: int) -> str:
            hours = ms // 3600000
            minutes = (ms % 3600000) // 60000
            seconds = (ms % 60000) // 1000
            centiseconds = (ms % 1000) // 10
            return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
            
        x_pct = float(layout.get("x", 0.08))
        y_pct = float(layout.get("y", 0.56))
        w_pct = float(layout.get("width", 0.84))
        h_pct = float(layout.get("height", 0.08))

        x_pct = max(0.0, min(0.95, x_pct))
        y_pct = max(0.0, min(0.95, y_pct))
        w_pct = max(0.10, min(1.0 - x_pct, w_pct))
        h_pct = max(0.04, min(1.0 - y_pct, h_pct))

        box_w = int(play_w * w_pct)
        box_h = int(play_h * h_pct)
        center_x = int(play_w * (x_pct + w_pct / 2))
        center_y = int(play_h * (y_pct + h_pct / 2))
        
        # Calculate responsive font size based on video dimensions
        if play_h > play_w:
            font_size = int(play_w * 0.055)
        else:
            font_size = int(play_h * 0.069)
            
        max_chars = max(16, min(42, int(box_w / (font_size * 0.46))))

        # Define border style and background colour based on mask_subtitle option
        if mask_subtitle:
            # Clean outline border style without ASS opaque box because we have the frosted glass band!
            border_style = 1
            outline_size = 3
            shadow_size = 0
            back_colour = "&H00000000"
        else:
            border_style = 3
            outline_size = max(1, int(stroke_size))
            shadow_size = 2
            back_colour = self._ass_alpha_black(bg_opacity)

        ass_lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {play_w}",
            f"PlayResY: {play_h}",
            "WrapStyle: 1",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,Arial,{font_size},&H00FFFFFF,&H0000FFFF,&H00000000,{back_colour},-1,0,0,0,100,100,0,0,{border_style},{outline_size},{shadow_size},5,20,20,0,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]
        
        for sub in new_subs:
            start_ms = sub.start.ordinal
            end_ms = sub.end.ordinal
            duration_ms = end_ms - start_ms
            
            if subtitle_style == "karaoke":
                words = sub.text.strip().split()
                if not words:
                    continue
                lengths = [len(w) for w in words]
                total_len = sum(lengths)
                total_cs = max(1, duration_ms // 10)
                
                ass_parts = []
                accumulated_cs = 0
                for i, word in enumerate(words):
                    if i < len(words) - 1:
                        cs = int(round(total_cs * (lengths[i] / total_len)))
                        accumulated_cs += cs
                    else:
                        cs = max(0, total_cs - accumulated_cs)
                    ass_parts.append(f"{{\\kf{cs}}}{word}")
                
                text = " ".join(ass_parts)
                start_str = ms_to_ass_time(start_ms)
                end_str = ms_to_ass_time(end_ms)
                ass_lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{{\\an5\\pos({center_x},{center_y})}}{text}")
                
            elif subtitle_style == "word_highlight":
                words = sub.text.strip().split()
                if not words:
                    continue
                lengths = [len(w) for w in words]
                total_len = sum(lengths)
                
                accumulated_ms = 0
                for i, word in enumerate(words):
                    if i < len(words) - 1:
                        word_dur = int(round(duration_ms * (lengths[i] / total_len)))
                    else:
                        word_dur = max(0, duration_ms - accumulated_ms)
                        
                    w_start = start_ms + accumulated_ms
                    w_end = w_start + word_dur
                    accumulated_ms += word_dur
                    
                    # Show ONLY the active word, with yellow color, bold and 15% zoom (Viral TikTok/Reels style)
                    line_text = f"{{\\c&H0000FFFF\\fscx115\\fscy115\\b1}}{words[i]}{{\\r}}"
                    
                    start_str = ms_to_ass_time(w_start)
                    end_str = ms_to_ass_time(w_end)
                    ass_lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{{\\an5\\pos({center_x},{center_y})}}{line_text}")
            else:
                start_str = ms_to_ass_time(start_ms)
                end_str = ms_to_ass_time(end_ms)
                text = self._wrap_subtitle_text(sub.text, max_chars)
                ass_lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{{\\an5\\pos({center_x},{center_y})}}{text}")
            
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write("\n".join(ass_lines))

    def render(
        self,
        video_path: Path,
        audio_path: Path,
        srt_path: Path,
        output_path: Path,
        metadata: dict,
        logo_path: Path = None,
        mask_subtitle: bool = True,
        render_subtitles: bool = True,
        subtitle_layout: dict = None,
        subtitle_style: str = "default",
        subtitle_cover_mode: str = "text_box_only",
        subtitle_bg_opacity: float = 0.42,
        subtitle_mask_padding_x: int = 20,
        subtitle_mask_padding_y: int = 12,
        ocr_sample_interval_sec: float = 0.75,
        ocr_crop_bottom_ratio: float = 0.45,
        debug_dir: Path = None,
        w_out: int = 1080,
        h_out: int = 1920,
        reframe_mode: str = "keep_original",
        crop_layout: dict = None,
        logo_position: str = "top_left",
        logo_layout: dict = None,
        asset_path: Path = None,
        asset_layout: dict = None,
        blur_masks: list = None,
    ) -> Path:
        """Renders the final output video with mixed audio, brand logo, and burned SRT."""
        logger.info(f"Rendering final output video to {output_path} ({w_out}x{h_out}, mode={reframe_mode}, logo_pos={logo_position}, logo_layout={logo_layout}, asset_layout={asset_layout}, blur_masks={blur_masks})...")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        w_in = metadata.get("width", 1920)
        h_in = metadata.get("height", 1080)
        
        filters = []
        
        # 1. Video aspect ratio reframing & padding filters
        if reframe_mode == "blur_background":
            if (w_in / h_in) > (w_out / h_out):
                # Landscape source to vertical target
                filters.extend([
                    f"[0:v]scale={w_out}:-2[scaled_fg]",
                    f"[0:v]scale=-2:{h_out},crop={w_out}:{h_out},boxblur=20:5[bg]",
                    f"[bg][scaled_fg]overlay=x=0:y=(H-h)/2[layout]"
                ])
            else:
                # Vertical source to landscape target
                filters.extend([
                    f"[0:v]scale=-2:{h_out}[scaled_fg]",
                    f"[0:v]scale={w_out}:-2,crop={w_out}:{h_out},boxblur=20:5[bg]",
                    f"[bg][scaled_fg]overlay=x=(W-w)/2:y=0[layout]"
                ])
        elif reframe_mode == "manual_crop" and crop_layout:
            cx = float(crop_layout.get("crop_x_percent", 0.342))
            cy = float(crop_layout.get("crop_y_percent", 0.0))
            cw = float(crop_layout.get("crop_width_percent", 0.316))
            ch = float(crop_layout.get("crop_height_percent", 1.0))
            
            x_px = int(cx * w_in)
            y_px = int(cy * h_in)
            w_px = int(cw * w_in)
            h_px = int(ch * h_in)
            
            filters.extend([
                f"[0:v]crop={w_px}:{h_px}:{x_px}:{y_px}[cropped]",
                f"[cropped]scale={w_out}:{h_out}[layout]"
            ])
        else:
            # Default scale and pad to keep aspect ratio
            filters.append(
                f"[0:v]scale={w_out}:{h_out}:force_original_aspect_ratio=decrease,pad={w_out}:{h_out}:(ow-iw)/2:(oh-ih)/2:black[layout]"
            )
            
        current_grid = "[layout]"
        
        # 2. Subtitle placement is user-selected. OCR/old-text detection is intentionally disabled.
        default_layout = {"x": 0.08, "y": 0.72, "width": 0.84, "height": 0.11}
        subtitle_layout = {**default_layout, **self._normalize_layout_keys(subtitle_layout)}
        if not render_subtitles:
            mask_subtitle = False
            subtitle_cover_mode = "none"

        opacity = max(0.0, min(1.0, float(subtitle_bg_opacity)))

        if render_subtitles:
            logger.info(
                "Using manual subtitle layout: "
                f"x={subtitle_layout['x']:.3f}, y={subtitle_layout['y']:.3f}, "
                f"w={subtitle_layout['width']:.3f}, h={subtitle_layout['height']:.3f}, "
                f"backplate_opacity={opacity:.2f}"
            )
            
        # Determine overlay indexes
        has_logo = logo_path and os.path.exists(logo_path) and os.path.getsize(logo_path) > 0
        
        asset_type = asset_layout.get("type", "image") if asset_layout else None
        has_asset = (asset_type == "image") and asset_path and os.path.exists(asset_path) and os.path.getsize(asset_path) > 0
        has_color_mask = (asset_type == "color")
        has_blur_mask = (asset_type == "blur")
        
        # Nếu logo mặc định trùng với vật thể đè (Asset) do người dùng tự kéo thả,
        # ta ẩn logo mặc định đi để chỉ vẽ theo vị trí kéo thả tùy chỉnh.
        if has_logo and has_asset:
            try:
                if Path(logo_path).resolve() == Path(asset_path).resolve():
                    has_logo = False
            except Exception:
                pass
        
        logo_input_index = None
        asset_input_index = None
        current_input_index = 2
        
        if has_logo:
            logo_input_index = current_input_index
            current_input_index += 1
            
        if has_asset:
            asset_input_index = current_input_index
            current_input_index += 1
            
        # 3. Logo/Watermark overlay (centered slightly below the top of the frame or preset coords)
        if has_logo:
            custom_x = logo_layout.get("x_percent") if logo_layout else None
            custom_y = logo_layout.get("y_percent") if logo_layout else None
            
            if custom_x is not None and custom_y is not None:
                expr = f"x=W*{custom_x}:y=H*{custom_y}"
            else:
                pos = logo_position or "top_left"
                if pos == "top_left":
                    expr = "x=W*0.05:y=H*0.05"
                elif pos == "top_right":
                    expr = "x=W-w-W*0.05:y=H*0.05"
                elif pos == "bottom_left":
                    expr = "x=W*0.05:y=H-h-H*0.05"
                elif pos == "bottom_right":
                    expr = "x=W-w-W*0.05:y=H-h-H*0.05"
                else: # top_center
                    expr = "x=(W-w)/2:y=120"
                
            # Scale logo to match custom width percentage if available
            custom_w = logo_layout.get("width_percent") if logo_layout else None
            logo_w = int(w_out * (float(custom_w) if custom_w is not None else 0.085))
            logo_w = (logo_w // 2) * 2
            filters.append(
                f"[{logo_input_index}:v]scale={logo_w}:-2[scaled_logo]"
            )
            filters.append(
                f"{current_grid}[scaled_logo]overlay={expr}[logoed]"
            )
            current_grid = "[logoed]"
            
        # 3.5 Customizable Asset overlay (resizable width/height & opacity)
        if has_asset:
            a_x = asset_layout.get("x_percent", 0.40) if asset_layout else 0.40
            a_y = asset_layout.get("y_percent", 0.08) if asset_layout else 0.08
            a_w = asset_layout.get("width_percent", 0.20) if asset_layout else 0.20
            a_h = asset_layout.get("height_percent", 0.08) if asset_layout else 0.08
            a_opacity = asset_layout.get("opacity", 1.0) if asset_layout else 1.0
            
            # Pre-calculate pixel dimensions to prevent FFmpeg coordinate scale errors
            px_w = int(w_out * a_w)
            px_h = int(h_out * a_h)
            
            filters.append(
                f"[{asset_input_index}:v]scale={px_w}:{px_h},format=rgba,colorchannelmixer=aa={a_opacity}[filtered_asset]"
            )
            filters.append(
                f"{current_grid}[filtered_asset]overlay=x=W*{a_x}:y=H*{a_y}[overlaid_asset]"
            )
            current_grid = "[overlaid_asset]"
        elif has_color_mask:
            a_x = asset_layout.get("x_percent", 0.40)
            a_y = asset_layout.get("y_percent", 0.08)
            a_w = asset_layout.get("width_percent", 0.20)
            a_h = asset_layout.get("height_percent", 0.08)
            a_opacity = asset_layout.get("opacity", 1.0)
            a_color = asset_layout.get("color", "#000000")
            
            color_hex = a_color.replace("#", "")
            
            px_x = int(w_out * a_x)
            px_y = int(h_out * a_y)
            px_w = int(w_out * a_w)
            px_h = int(h_out * a_h)
            
            filters.append(
                f"{current_grid}drawbox=x={px_x}:y={px_y}:w={px_w}:h={px_h}:color=0x{color_hex}@{a_opacity}:t=fill[masked]"
            )
            current_grid = "[masked]"
        elif has_blur_mask:
            a_x = asset_layout.get("x_percent", 0.40)
            a_y = asset_layout.get("y_percent", 0.08)
            a_w = asset_layout.get("width_percent", 0.20)
            a_h = asset_layout.get("height_percent", 0.08)
            a_opacity = asset_layout.get("opacity", 1.0)
            
            px_x = (max(0, min(w_out - 10, int(w_out * a_x))) // 2) * 2
            px_y = (max(0, min(h_out - 10, int(h_out * a_y))) // 2) * 2
            px_w = (max(10, min(w_out - px_x, int(w_out * a_w))) // 2) * 2
            px_h = (max(10, min(h_out - px_y, int(h_out * a_h))) // 2) * 2
            
            # Cap boxblur radius to prevent FFmpeg crash for small dimensions
            max_allowed = min(px_w // 4, px_h // 4)
            blur_radius = max(1, min(max_allowed, int(a_opacity * 30)))
            
            filters.append(
                f"{current_grid}split[orig_sp][for_blur]"
            )
            filters.append(
                f"[for_blur]crop={px_w}:{px_h}:{px_x}:{px_y},boxblur={blur_radius}:5[blurred_crop]"
            )
            filters.append(
                f"[orig_sp][blurred_crop]overlay=x={px_x}:y={px_y}[masked]"
            )
            current_grid = "[masked]"
            
        # 3.6 Multiple Sequential Blur Masks
        if blur_masks:
            for idx, mask in enumerate(blur_masks):
                m_x = mask.get("x_percent", 0.40)
                m_y = mask.get("y_percent", 0.08)
                m_w = mask.get("width_percent", 0.20)
                m_h = mask.get("height_percent", 0.08)
                m_opacity = mask.get("opacity", 0.6)
                
                px_x = (max(0, min(w_out - 10, int(w_out * m_x))) // 2) * 2
                px_y = (max(0, min(h_out - 10, int(h_out * m_y))) // 2) * 2
                px_w = (max(10, min(w_out - px_x, int(w_out * m_w))) // 2) * 2
                px_h = (max(10, min(h_out - px_y, int(h_out * m_h))) // 2) * 2
                
                # Cap boxblur radius to prevent FFmpeg crash for small dimensions
                max_allowed = min(px_w // 4, px_h // 4)
                blur_radius = max(1, min(max_allowed, int(m_opacity * 30)))
                
                next_grid = f"[masked_seq_{idx}]"
                filters.append(
                    f"{current_grid}split[orig_seq_{idx}][for_blur_seq_{idx}]"
                )
                filters.append(
                    f"[for_blur_seq_{idx}]crop={px_w}:{px_h}:{px_x}:{px_y},boxblur={blur_radius}:5[blurred_crop_seq_{idx}]"
                )
                filters.append(
                    f"[orig_seq_{idx}][blurred_crop_seq_{idx}]overlay=x={px_x}:y={px_y}{next_grid}"
                )
                current_grid = next_grid
            
        # 4. Burn-in translation subtitles using native ASS backplate box (100x faster, zero-split, dynamic width)
        if render_subtitles:
            ass_path = srt_path.with_suffix(".ass")
            self._convert_srt_to_ass(
                srt_path,
                ass_path,
                subtitle_layout=subtitle_layout,
                bg_opacity=subtitle_bg_opacity,
                stroke_size=3,
                play_w=w_out,
                play_h=h_out,
                subtitle_style=subtitle_style,
                mask_subtitle=mask_subtitle,
            )
            
            # Apply frosted glass blur band filter if mask_subtitle is enabled
            if mask_subtitle:
                layout = self._normalize_layout_keys(subtitle_layout)
                y_pct = float(layout.get("y", 0.72))
                h_pct = float(layout.get("height", 0.11))
                
                band_y = (int(h_out * y_pct) // 2) * 2
                band_height = (int(h_out * h_pct) // 2) * 2
                
                fade_px = int(band_height * 0.3)
                if fade_px < 1:
                    fade_px = 1
                    
                alpha_expr = f"255*min(1,Y/{fade_px})*min(1,({band_height}-Y)/{fade_px})"
                
                next_grid = "[v_bg]"
                filters.append(
                    f"{current_grid}split=2[main_bg][fg_band]"
                )
                filters.append(
                    f"[fg_band]crop=iw:{band_height}:0:{band_y},boxblur=15:5,colorchannelmixer=rr=0.5:gg=0.5:bb=0.5[blurred_band]"
                )
                filters.append(
                    f"[blurred_band]format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{alpha_expr}'[feathered_blur]"
                )
                filters.append(
                    f"[main_bg][feathered_blur]overlay=0:{band_y}:shortest=1{next_grid}"
                )
                current_grid = next_grid
            
            escaped_ass = self._escape_windows_path(ass_path)
            filters.append(
                f"{current_grid}subtitles='{escaped_ass}'[outv]"
            )
        else:
            logger.info("Subtitle rendering disabled for this job.")
            filters.append(f"{current_grid}null[outv]")
        
        filter_complex = ";".join(filters)
        
        # Assemble FFmpeg execution args
        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-i", str(video_path),
            "-i", str(audio_path)
        ]
        
        if has_logo:
            cmd.extend(["-i", str(logo_path)])
            
        if has_asset:
            cmd.extend(["-i", str(asset_path)])
            
        best_encoder = self._detect_best_encoder()
        encoder_args = ["-c:v", best_encoder]
        if best_encoder == "libx264":
            encoder_args.extend(["-preset", "ultrafast", "-crf", "21"])
        elif best_encoder == "h264_nvenc":
            encoder_args.extend(["-preset", "fast"])
        elif best_encoder == "h264_qsv":
            encoder_args.extend(["-preset", "fast"])
        elif best_encoder == "h264_amf":
            encoder_args.extend(["-quality", "speed"])
        elif best_encoder == "h264_mf":
            pass

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "1:a"
        ])
        cmd.extend(encoder_args)
        cmd.extend([
            "-pix_fmt", "yuv420p",
            "-colorspace", "bt709",
            "-color_trc", "bt709",
            "-color_primaries", "bt709",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_path)
        ])
        
        logger.info(f"FFmpeg render command: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
            logger.info("Video rendering completed successfully.")
            return output_path
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg render process failed with code {e.returncode}")
            logger.error(f"FFmpeg stdout: {e.stdout}")
            logger.error(f"FFmpeg stderr: {e.stderr}")
            raise RenderError(f"FFmpeg render failed: {e.stderr}")
        except Exception as e:
            logger.error(f"Unexpected rendering failure: {e}")
            raise RenderError(f"Video rendering failed: {e}")
