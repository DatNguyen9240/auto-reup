import os
import subprocess
from pathlib import Path
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
                f"[0:v]scale={w_out}:{h_out}:force_original_aspect_ratio=increase,crop={w_out}:{h_out},boxblur=20:5[bg]"
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
        
        # 2. Chinese subtitle cover-up (Semi-transparent black box)
        if mask_subtitle:
            # Compute subtitle region dynamically relative to the foreground video box vertical span
            h_fit = int(w_out * h_in / w_in)
            y_fit = (h_out - h_fit) // 2
            
            # Subtitles typically occupy bottom 16% of the foreground video box
            mask_y = y_fit + int(h_fit * 0.81)
            mask_h = int(h_fit * 0.15)
            mask_w = int(w_out * 0.85)
            mask_x = (w_out - mask_w) // 2
            
            filters.append(
                f"{current_grid}drawbox=x={mask_x}:y={mask_y}:w={mask_w}:h={mask_h}:color=black@0.65:t=fill[masked]"
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
            
        # 4. Burn-in translation subtitles (SRT)
        escaped_srt = self._escape_windows_path(srt_path)
        # FontName can be Arial or custom, Alignment=2 is bottom center, MarginV=120 ensures safe-zone layout
        sub_style = (
            "force_style='FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=2.5,Shadow=0,Alignment=2,MarginV=120'"
        )
        filters.append(
            f"{current_grid}subtitles='{escaped_srt}':{sub_style}[outv]"
        )
        
        filter_complex = ";".join(filters)
        
        # Assemble FFmpeg execution args
        cmd = [
            "ffmpeg", "-y",
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
            "-preset", "medium",
            "-crf", "21",
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
