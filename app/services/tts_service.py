import ffmpeg
from pathlib import Path
from typing import List
from app.models.segment import Segment
from app.providers.tts_base import TTSProvider
from app.core.errors import TTSError
from app.utils.logger import get_logger

logger = get_logger("TTSService")

class TTSService:
    def __init__(self, tts_provider: TTSProvider):
        self.tts_provider = tts_provider

    def get_audio_duration_ms(self, file_path: Path) -> int:
        """Returns the duration of an audio file in milliseconds."""
        try:
            probe = ffmpeg.probe(str(file_path))
            duration = float(probe['format']['duration'])
            return int(duration * 1000)
        except Exception as e:
            logger.error(f"Failed to probe duration of {file_path}: {e}")
            raise TTSError(f"Failed to get audio duration: {e}")

    def adjust_audio_speed(self, input_path: Path, output_path: Path, ratio: float):
        """Adjusts the speed of an audio file using FFmpeg atempo filter."""
        logger.info(f"Adjusting speed of {input_path} by ratio {ratio:.2f}")
        try:
            # atempo only supports 0.5 to 2.0. Chain them if ratio > 2.0
            stream = ffmpeg.input(str(input_path))
            
            # Construct atempo filters
            r = ratio
            filters = []
            while r > 2.0:
                filters.append("atempo=2.0")
                r /= 2.0
            while r < 0.5:
                filters.append("atempo=0.5")
                r /= 0.5
            
            filters.append(f"atempo={r:.4f}")
            filter_str = ",".join(filters)
            
            out = ffmpeg.output(stream, str(output_path), af=filter_str)
            ffmpeg.run(out, overwrite_output=True, capture_stdout=True, capture_stderr=True)
        except ffmpeg.Error as e:
            stderr = e.stderr.decode("utf-8") if e.stderr else str(e)
            logger.error(f"FFmpeg speed adjustment failed: {stderr}")
            raise TTSError(f"FFmpeg speed adjustment failed: {stderr}")
        except Exception as e:
            logger.error(f"Speed adjustment failed: {e}")
            raise TTSError(f"Speed adjustment failed: {e}")

    async def generate_voiceovers(
        self, 
        segments: List[Segment], 
        work_dir: Path, 
        voice: str, 
        rate: str = "+0%", 
        pitch: str = "+0Hz"
    ) -> List[Segment]:
        """Generates speech audio for all segments, auto-scaling speed if it exceeds the original segment duration."""
        logger.info(f"Generating voiceovers for {len(segments)} segments in {work_dir}")
        tts_dir = work_dir / "tts"
        tts_dir.mkdir(parents=True, exist_ok=True)
        
        for segment in segments:
            if not segment.tts_text.strip():
                segment.status = "tts_generated"
                continue
                
            raw_path = tts_dir / f"seg_{segment.id}_raw.mp3"
            final_path = tts_dir / f"seg_{segment.id}.wav"
            
            # Step 1: Generate Raw Speech
            await self.tts_provider.generate_tts(
                text=segment.tts_text,
                output_path=raw_path,
                voice=voice,
                rate=rate,
                pitch=pitch
            )
            
            # Step 2: Probe raw TTS duration
            raw_duration_ms = self.get_audio_duration_ms(raw_path)
            target_duration_ms = max(segment.duration_ms, 100)
            
            # Step 3: Speed adjust if necessary
            if raw_duration_ms > target_duration_ms:
                ratio = raw_duration_ms / target_duration_ms
                # Clamp ratio to reasonable limits [0.5, 4.0]
                ratio = min(max(ratio, 0.5), 4.0)
                try:
                    self.adjust_audio_speed(raw_path, final_path, ratio)
                except Exception as e:
                    logger.warning(f"Speed adjustment failed for segment {segment.id}, using raw: {e}")
                    # Fallback: convert raw directly to wav
                    try:
                        ffmpeg.run(
                            ffmpeg.output(ffmpeg.input(str(raw_path)), str(final_path)),
                            overwrite_output=True, capture_stdout=True, capture_stderr=True
                        )
                    except Exception as copy_err:
                        raise TTSError(f"Failed to process fallback audio for segment {segment.id}: {copy_err}")
            else:
                # No speed adjustment needed, convert raw (mp3) to wav
                try:
                    ffmpeg.run(
                        ffmpeg.output(ffmpeg.input(str(raw_path)), str(final_path)),
                        overwrite_output=True, capture_stdout=True, capture_stderr=True
                    )
                except Exception as e:
                    logger.error(f"Failed to convert raw TTS to wav for segment {segment.id}: {e}")
                    raise TTSError(f"Audio format conversion failed: {e}")
                    
            segment.tts_path = str(final_path)
            segment.status = "tts_generated"
            
        logger.info("All segment voiceovers generated and processed successfully.")
        return segments
