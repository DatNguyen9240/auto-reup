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

        play_w = 1080
        play_h = 1920
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
    ) -> Path:
        """Renders the final 9:16 portrait video with mixed audio, masked subtitles, brand logo, and burned SRT."""
        logger.info(f"Rendering final output video to {output_path}...")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        w_in = metadata.get("width", 1920)
        h_in = metadata.get("height", 1080)
        
        # Standard vertical video output canvas: 1080x1920
        w_out = 1080
        h_out = 1920
        
        filters = []
        
        # 1. Video aspect ratio conversion (Horizontal/Square -> 9:16 Blurred Background)
        if w_in >= h_in:
            # Input is horizontal or square: make blurred background + centered foreground
            filters.append(
                f"[0:v]scale={w_out}:{h_out}:force_original_aspect_ratio=increase,crop={w_out}:{h_out},boxblur=20:1[bg]"
            )
            filters.append(
                f"[0:v]scale={w_out}:{h_out}:force_original_aspect_ratio=decrease[fg]"
            )
            filters.append(
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[layout]"
            )
        else:
            # Input is already vertical: scale/pad to exactly fit 1080x1920
            filters.append(
                f"[0:v]scale={w_out}:{h_out}:force_original_aspect_ratio=decrease,pad={w_out}:{h_out}:(ow-iw)/2:(oh-ih)/2[layout]"
            )
            
        current_grid = "[layout]"
        
        # 2. Subtitle placement is user-selected. OCR/old-text detection is intentionally disabled.
        default_layout = {"x": 0.08, "y": 0.72, "width": 0.84, "height": 0.11}
        subtitle_layout = {**default_layout, **(subtitle_layout or {})}
        if not render_subtitles:
            mask_subtitle = False
            subtitle_cover_mode = "none"

        cover_mode = subtitle_cover_mode or ("fixed_bottom_bar" if mask_subtitle else "none")
        opacity = max(0.0, min(1.0, float(subtitle_bg_opacity)))

        if render_subtitles:
            logger.info(
                "Using manual subtitle layout: "
                f"x={subtitle_layout['x']:.3f}, y={subtitle_layout['y']:.3f}, "
                f"w={subtitle_layout['width']:.3f}, h={subtitle_layout['height']:.3f}, "
                f"backplate_opacity={opacity:.2f}"
            )
            
        # 3. Logo/Watermark overlay (centered slightly below the top of the frame)
        has_logo = logo_path and os.path.exists(logo_path) and os.path.getsize(logo_path) > 0
        if has_logo:
            # overlay logo at horizontal center, 120 pixels from top
            filters.append(
                f"{current_grid}[2:v]overlay=x=(W-w)/2:y=120[logoed]"
            )
            current_grid = "[logoed]"
            
        # 4. Burn-in translation subtitles (Convert SRT to ASS for pixel-perfect alignment and scaling)
        if render_subtitles:
            ass_path = srt_path.with_suffix(".ass")
            self._convert_srt_to_ass(
                srt_path,
                ass_path,
                subtitle_layout=subtitle_layout,
                bg_opacity=opacity,
                stroke_size=3,
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
