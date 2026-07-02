import ffmpeg
from pathlib import Path
from app.core.errors import AudioExtractionError
from app.utils.logger import get_logger

logger = get_logger("AudioExtractor")

class AudioExtractor:
    def extract(self, video_path: Path, output_wav_path: Path) -> Path:
        """Extracts audio from a video file into a 16kHz, mono WAV file."""
        logger.info(f"Extracting audio from {video_path} to {output_wav_path}")
        if not Path(video_path).exists():
            raise AudioExtractionError(f"Video file not found: {video_path}")
            
        output_wav_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # -acodec pcm_s16le -ac 1 -ar 16000
            # Apply FFT-based noise reduction (afftdn) and voice bandpass filtering (200Hz - 3200Hz) to improve Whisper transcription
            stream = ffmpeg.input(str(video_path))
            audio = stream.audio
            out = ffmpeg.output(
                audio, 
                str(output_wav_path), 
                acodec="pcm_s16le", 
                ac=1, 
                ar=16000,
                af="afftdn,highpass=f=200,lowpass=f=3200"
            )
            # Run FFmpeg synchronously and overwrite existing output
            ffmpeg.run(out, overwrite_output=True, capture_stdout=True, capture_stderr=True)
            logger.info("Audio extraction and noise-reduction completed successfully.")
            return output_wav_path
        except ffmpeg.Error as e:
            stderr = e.stderr.decode("utf-8") if e.stderr else str(e)
            logger.error(f"FFmpeg error: {stderr}")
            raise AudioExtractionError(f"FFmpeg audio extraction failed: {stderr}")
        except Exception as e:
            logger.error(f"Unexpected extraction error: {e}")
            raise AudioExtractionError(f"Audio extraction failed: {e}")
