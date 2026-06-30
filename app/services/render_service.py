import os
import subprocess
from pathlib import Path
import pysrt
from app.core.errors import RenderError
from app.utils.logger import get_logger

logger = get_logger("RenderService")

class RenderService:
    def _escape_windows_path(self, path: Path) -> str:
        """Escapes Windows paths for use within FFmpeg filter arguments (like subtitles)."""
        p_str = str(path.resolve()).replace("\\", "/")
        if ":" in p_str:
            drive, rest = p_str.split(":", 1)
            p_str = f"{drive}\\:{rest}"
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

    def _convert_srt_to_ass(
        self,
        srt_path: Path,
        ass_path: Path,
        subtitle_layout: dict,
        bg_opacity: float,
        stroke_size: int = 3,
        play_w: int = 1080,
        play_h: int = 1920,
    ):
        """Converts SRT to ASS using a user-selected normalized subtitle box."""
        subs = pysrt.open(str(srt_path), encoding="utf-8")
        
        def ms_to_ass_time(ms: int) -> str:
            hours = ms // 3600000
            minutes = (ms % 3600000) // 60000
            seconds = (ms % 60000) // 1000
            centiseconds = (ms % 1000) // 10
            return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
            
        layout = subtitle_layout or {}
        x_pct = float(layout.get("x", 0.08))
        y_pct = float(layout.get("y", 0.72))
        w_pct = float(layout.get("width", 0.84))
        h_pct = float(layout.get("height", 0.11))

        x_pct = max(0.0, min(0.95, x_pct))
        y_pct = max(0.0, min(0.95, y_pct))
        w_pct = max(0.10, min(1.0 - x_pct, w_pct))
        h_pct = max(0.04, min(1.0 - y_pct, h_pct))

        box_w = int(play_w * w_pct)
        box_h = int(play_h * h_pct)
        center_x = int(play_w * (x_pct + w_pct / 2))
        center_y = int(play_h * (y_pct + h_pct / 2))
        font_size = int(min(max(34, box_h * 0.34), max(42, box_w / 12), 72))
        max_chars = max(16, min(42, int(box_w / (font_size * 0.46))))
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
            f"Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,{back_colour},-1,0,0,0,100,100,0,0,3,{max(1, int(stroke_size))},2,5,20,20,0,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]
        
        for sub in subs:
            start_str = ms_to_ass_time(sub.start.ordinal)
            end_str = ms_to_ass_time(sub.end.ordinal)
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
        logo_position: str = "top_center",
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
                    f"[0:v]scale={w_out}:-1[scaled_fg]",
                    f"[0:v]scale=-1:{h_out},crop={w_out}:{h_out},boxblur=20:5[bg]",
                    f"[bg][scaled_fg]overlay=x=0:y=(H-h)/2[layout]"
                ])
            else:
                # Vertical source to landscape target
                filters.extend([
                    f"[0:v]scale=-1:{h_out}[scaled_fg]",
                    f"[0:v]scale={w_out}:-1,crop={w_out}:{h_out},boxblur=20:5[bg]",
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
        subtitle_layout = {**default_layout, **(subtitle_layout or {})}
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
                pos = logo_position or "top_center"
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
                
            # Scale logo to match the 12.5% width of the editor box relative to workspace
            logo_w = int(w_out * 0.125)
            filters.append(
                f"[{logo_input_index}:v]scale={logo_w}:-1[scaled_logo]"
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
            blur_radius = max(3, min(40, int(a_opacity * 30)))
            
            px_x = max(0, min(w_out - 10, int(w_out * a_x)))
            px_y = max(0, min(h_out - 10, int(h_out * a_y)))
            px_w = max(10, min(w_out - px_x, int(w_out * a_w)))
            px_h = max(10, min(h_out - px_y, int(h_out * a_h)))
            
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
                blur_radius = max(3, min(40, int(m_opacity * 30)))
                
                px_x = max(0, min(w_out - 10, int(w_out * m_x)))
                px_y = max(0, min(h_out - 10, int(h_out * m_y)))
                px_w = max(10, min(w_out - px_x, int(w_out * m_w)))
                px_h = max(10, min(h_out - px_y, int(h_out * m_h)))
                
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
            )
            
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
            
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "1:a",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "21",
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
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
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
