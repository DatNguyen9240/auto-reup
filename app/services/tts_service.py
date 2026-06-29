import ffmpeg
import asyncio
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
        
        for idx, segment in enumerate(segments):
            if not segment.tts_text.strip():
                segment.status = "tts_generated"
                logger.info(f"[{idx+1}/{len(segments)}] Skipping empty TTS segment {segment.id}.")
                continue
                
            logger.info(f"[{idx+1}/{len(segments)}] Generating voiceover for segment {segment.id}: '{segment.tts_text[:30]}...'")
            import hashlib
            param_str = f"{segment.tts_text}|{voice}|{rate}|{pitch}"
            param_hash = hashlib.md5(param_str.encode('utf-8')).hexdigest()[:12]
            
            raw_path = tts_dir / f"seg_{segment.id}_{param_hash}_raw.mp3"
            final_path = tts_dir / f"seg_{segment.id}_{param_hash}.wav"
            
            # Clean up old/stale files for this segment id if they exist to prevent disk bloat
            for old_file in tts_dir.glob(f"seg_{segment.id}_*"):
                if old_file.name not in [raw_path.name, final_path.name]:
                    try:
                        old_file.unlink()
                    except Exception:
                        pass
            
            # Step 1: Generate Raw Speech (Skip if raw file already exists to save time and API calls)
            if not raw_path.exists() or raw_path.stat().st_size == 0:
                await self.tts_provider.generate_tts(
                    text=segment.tts_text,
                    output_path=raw_path,
                    voice=voice,
                    rate=rate,
                    pitch=pitch
                )
            
            # Step 2: Probe raw TTS duration
            raw_duration_ms = self.get_audio_duration_ms(raw_path)
            
            # Calculate available time to next segment to prevent overlapping voiceover
            if idx < len(segments) - 1:
                available_time_ms = max(segments[idx+1].start_ms - segment.start_ms, 100)
            else:
                available_time_ms = max(segment.duration_ms, 100)
            
            # Step 3: Speed adjust (baseline speed is 1.1x, and up to 1.8x to prevent overlap)
            ratio = raw_duration_ms / available_time_ms
            ratio = max(1.1, min(ratio, 1.8))
            
            logger.info(
                f"Segment {segment.id}: raw duration {raw_duration_ms}ms, available time {available_time_ms}ms. "
                f"Applying speed factor {ratio:.2f}x."
            )
            try:
                self.adjust_audio_speed(raw_path, final_path, ratio)
            except Exception as e:
                logger.warning(f"Speed adjustment failed for segment {segment.id}, fallback to speed-adjusted copy: {e}")
                try:
                    ffmpeg.run(
                        ffmpeg.output(ffmpeg.input(str(raw_path)), str(final_path), af=f"atempo={ratio:.4f}"),
                        overwrite_output=True, capture_stdout=True, capture_stderr=True
                    )
                except Exception as copy_err:
                    # Final fallback: convert raw directly to wav (1.0x)
                    try:
                        ffmpeg.run(
                            ffmpeg.output(ffmpeg.input(str(raw_path)), str(final_path)),
                            overwrite_output=True, capture_stdout=True, capture_stderr=True
                        )
                    except Exception as final_err:
                        raise TTSError(f"Failed to process fallback audio for segment {segment.id}: {final_err}")
                    
            segment.tts_path = str(final_path)
            segment.status = "tts_generated"
            logger.info(f"[{idx+1}/{len(segments)}] Completed voiceover for segment {segment.id}: {final_path.name}")
            
            # Rate-limiting guard: Add a short sleep between consecutive synthesis requests
            await asyncio.sleep(0.5)
            
        logger.info("All segment voiceovers generated and processed successfully.")
        return segments
