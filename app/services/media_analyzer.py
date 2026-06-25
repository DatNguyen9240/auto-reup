import ffmpeg
from pathlib import Path
from app.core.errors import MediaAnalyzerError
from app.utils.logger import get_logger

logger = get_logger("MediaAnalyzer")

class MediaAnalyzer:
    def analyze(self, video_path: Path) -> dict:
        """Probes a video file using FFprobe to get metadata."""
        logger.info(f"Analyzing media file: {video_path}")
        if not Path(video_path).exists():
            raise MediaAnalyzerError(f"Video file not found at {video_path}")
            
        try:
            probe = ffmpeg.probe(str(video_path))
            
            # Find video stream
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            audio_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'audio'), None)
            
            if not video_stream:
                raise MediaAnalyzerError("No video stream found in the media file.")
                
            width = int(video_stream['width'])
            height = int(video_stream['height'])
            duration = float(probe['format']['duration'])
            
            # Recommend aspect ratio / crop mode
            orientation = "horizontal" if width > height else "vertical"
            if width == height:
                orientation = "square"
                
            crop_mode = "center_crop"
            if orientation == "horizontal":
                crop_mode = "blurred_bg" # Default crop option for horizontal to vertical 9:16
                
            metadata = {
                "width": width,
                "height": height,
                "duration": duration,
                "orientation": orientation,
                "crop_mode": crop_mode,
                "has_audio": audio_stream is not None,
                "codec": video_stream.get("codec_name", "unknown")
            }
            logger.info(f"Analysis complete: {metadata}")
            return metadata
            
        except Exception as e:
            logger.error(f"FFprobe failed: {e}")
            raise MediaAnalyzerError(f"Failed to analyze media file: {e}")
