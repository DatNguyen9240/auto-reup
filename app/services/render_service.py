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

    def _convert_srt_to_ass(self, srt_path: Path, ass_path: Path, margin_v: int, mask_subtitle: bool, font_size: int = 38):
        """Converts an SRT file to an ASS file with 1080x1920 layout and specified MarginV."""
        subs = pysrt.open(str(srt_path), encoding="utf-8")
        
        def ms_to_ass_time(ms: int) -> str:
            hours = ms // 3600000
            minutes = (ms % 3600000) // 60000
            seconds = (ms % 60000) // 1000
            centiseconds = (ms % 1000) // 10
            return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
            
        # Select style options based on mask_subtitle
        if mask_subtitle:
            border_style = 3  # Opaque background box
            outline = 10      # Padding for background box
        else:
            border_style = 1  # Standard outline
            outline = 3       # Thin outline border
            
        ass_lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,{border_style},{outline},2,2,80,80,{margin_v},1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]
        
        for sub in subs:
            start_str = ms_to_ass_time(sub.start.ordinal)
            end_str = ms_to_ass_time(sub.end.ordinal)
            # Replace newline in SRT with ASS newline \N
            text = sub.text.replace("\n", "\\N")
            ass_lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}")
            
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
        mask_subtitle: bool = True
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
        
        # 2. Chinese subtitle cover-up (Draw solid black bar to fully cover background hardsubs)
        # Compute subtitle region dynamically relative to the foreground video box vertical span
        h_fit = int(w_out * h_in / w_in) if w_in >= h_in else h_out
        y_fit = (h_out - h_fit) // 2 if w_in >= h_in else 0
        
        # Subtitles typically occupy bottom 16-18% of the foreground video box
        mask_y = y_fit + int(h_fit * 0.79)
        mask_h = int(h_fit * 0.18)
        
        if mask_subtitle:
            # Draw a full-width solid black bar at the subtitle location to completely hide background subtitles
            filters.append(
                f"{current_grid}drawbox=x=0:y={mask_y}:w={w_out}:h={mask_h}:color=black@0.95:t=fill[masked]"
            )
            current_grid = "[masked]"
            
        # 3. Logo/Watermark overlay (centered slightly below the top of the frame)
        has_logo = logo_path and os.path.exists(logo_path) and os.path.getsize(logo_path) > 0
        if has_logo:
            # overlay logo at horizontal center, 120 pixels from top
            filters.append(
                f"{current_grid}[2:v]overlay=x=(W-w)/2:y=120[logoed]"
            )
            current_grid = "[logoed]"
            
        # 4. Burn-in translation subtitles (Convert SRT to ASS for pixel-perfect alignment and scaling)
        # Position the bottom line of subtitle text exactly 12px above the bottom of the old subtitle area
        margin_v = h_out - (mask_y + mask_h) + 12
        ass_path = srt_path.with_suffix(".ass")
        # Since we draw a full-width background black bar via drawbox, we use standard clean outline subtitles
        self._convert_srt_to_ass(srt_path, ass_path, margin_v=margin_v, mask_subtitle=False, font_size=42)
        
        escaped_ass = self._escape_windows_path(ass_path)
        filters.append(
            f"{current_grid}subtitles='{escaped_ass}'[outv]"
        )
        
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
