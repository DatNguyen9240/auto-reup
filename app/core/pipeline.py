import os
import shutil
import json
import asyncio
from pathlib import Path
from typing import List, Optional
import pysrt

from app.config import settings

from app.models.job import Job
from app.models.segment import Segment
from app.storage.json_store import JsonStore
from app.services.media_analyzer import MediaAnalyzer
from app.services.audio_extractor import AudioExtractor
from app.providers.llm_translate_provider import LLMTranslateProvider
from app.providers.edge_tts_provider import EdgeTTSProvider
from app.services.tts_service import TTSService
from app.services.audio_mixer import AudioMixer
from app.services.render_service import RenderService
from app.core.errors import AutoToolError
from app.utils.logger import get_logger
from app.utils.file_utils import ensure_dir, write_json

logger = get_logger("Pipeline")

import logging

class FlushingFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

class PipelineRunner:
    def __init__(self, projects_dir: Path):
        self.projects_dir = Path(projects_dir)
        self.store = JsonStore(self.projects_dir)
        self.analyzer = MediaAnalyzer()
        self.extractor = AudioExtractor()
        self.tts_provider = EdgeTTSProvider()
        self.tts_service = TTSService(self.tts_provider)
        self.mixer = AudioMixer()
        self.render_service = RenderService()
        self.translator = LLMTranslateProvider()

    def _get_dest_video(self, work_dir: Path) -> Path:
        """Safely resolves the input video path in the work directory."""
        matches = list(work_dir.glob("input.*"))
        if not matches:
            raise AutoToolError(f"No input video file found in work directory: {work_dir}")
        return matches[0]

    def create_job(self, input_path: str, job_id: str) -> Job:
        path_str = str(input_path)
        if not (path_str.startswith("http://") or path_str.startswith("https://")):
            path_str = str(Path(input_path).resolve())
        job = Job(
            job_id=job_id,
            status="created",
            input_path=path_str,
            output_path=str((self.projects_dir / job_id / "output" / "final.mp4").resolve())
        )
        self.store.save_job(job)
        return job

    async def run(
        self, 
        job_id: str, 
        tone: str = "review_phim", 
        voice: str = "vi-VN-HoaiMyNeural",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        bgm_name: str = None,
        logo_path: Path = None,
        mask_subtitle: bool = True
    ):
        job = self.store.load_job(job_id)
        if not job:
            raise AutoToolError(f"Job {job_id} not found.")

        def check_cancellation():
            curr = self.store.load_job(job_id)
            if not curr or curr.status == "failed" or curr.status == "cancelled":
                raise AutoToolError("Job bị ngắt bởi người dùng.")

        # Apply Emotion Preset mapping if defaults are used and tone has a preset
        EMOTION_PRESETS = {
            "funny": {"rate": "+8%", "pitch": "+4Hz", "bgm": "funny_loop"},
            "sad": {"rate": "-10%", "pitch": "-5Hz", "bgm": "sad_loop"},
            "drama": {"rate": "-4%", "pitch": "-3Hz", "bgm": "dramatic_loop"},
            "serious": {"rate": "-5%", "pitch": "-2Hz", "bgm": None},
            "energetic": {"rate": "+10%", "pitch": "+3Hz", "bgm": None}
        }
        
        if tone in EMOTION_PRESETS:
            preset = EMOTION_PRESETS[tone]
            if rate == "+0%":
                rate = preset["rate"]
                logger.info(f"Applying preset rate '{rate}' for tone '{tone}'")
            if pitch == "+0Hz":
                pitch = preset["pitch"]
                logger.info(f"Applying preset pitch '{pitch}' for tone '{tone}'")
            if bgm_name is None and preset.get("bgm"):
                bgm_name = preset["bgm"]
                logger.info(f"Applying preset BGM '{bgm_name}' for tone '{tone}'")

        job.status = "running"
        self.store.save_job(job)
        
        job_dir = self.projects_dir / job_id
        work_dir = job_dir / "work"
        output_dir = job_dir / "output"
        
        ensure_dir(work_dir)
        ensure_dir(output_dir)
        
        try:
            import logging
            log_file = job_dir / "run.log"
            file_handler = FlushingFileHandler(str(log_file), encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            logger.addHandler(file_handler)
            
            # Step 1: Intake
            check_cancellation()
            if job.steps.get("intake", "pending") == "pending":
                job.current_step = "intake"
                self.store.save_job(job)
                logger.info("--- Step 1: Intake ---")
                
                if job.input_path.startswith("http://") or job.input_path.startswith("https://"):
                    logger.info(f"Input is a URL. Downloading automatically: {job.input_path}")
                    dest_video = work_dir / "input.mp4"
                    
                    is_douyin = "douyin.com" in job.input_path or "v.douyin.com" in job.input_path
                    if not is_douyin:
                        logger.info("Using yt-dlp to download URL with console feedback...")
                        class YTDLPLogger:
                            def debug(self, msg):
                                if msg.startswith('[download]'):
                                    logger.info(msg)
                            def info(self, msg):
                                logger.info(msg)
                            def warning(self, msg):
                                logger.warning(msg)
                            def error(self, msg):
                                logger.error(msg)
                        
                        import yt_dlp
                        ydl_opts = {
                            'outtmpl': str(dest_video),
                            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                            'logger': YTDLPLogger(),
                            'quiet': False
                        }
                        def run_ytdl():
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                ydl.download([job.input_path])
                        await asyncio.get_event_loop().run_in_executor(None, run_ytdl)
                        info = {"title": job_id, "duration": 0}
                    else:
                        from app.services.downloader import PlaywrightDownloaderService
                        downloader = PlaywrightDownloaderService()
                        try:
                            # Download using Playwright Downloader
                            info = await downloader.download_video_async(job.input_path, dest_video)
                        except Exception as e:
                            logger.error(f"Download failed: {e}")
                            raise AutoToolError(f"Failed to download video from URL: {e}")
                        
                    # Save the downloaded video metadata
                    metadata_path = work_dir / "origin_metadata.json"
                    write_json(metadata_path, info)
                    logger.info(f"Metadata saved to: {metadata_path}")
                else:
                    input_video = Path(job.input_path)
                    if not input_video.exists():
                        raise AutoToolError(f"Input video not found at: {input_video}")
                    
                    # Copy input video to work dir as input.mp4 (or matching suffix)
                    dest_video = work_dir / f"input{input_video.suffix}"
                    shutil.copy2(input_video, dest_video)
                    
                    # Copy sidecar SRT if exists next to the source video
                    sidecar_srt = input_video.with_suffix(".srt")
                    if sidecar_srt.exists():
                        shutil.copy2(sidecar_srt, work_dir / "input.srt")
                        logger.info(f"Imported sidecar SRT: {sidecar_srt}")
                    
                job.steps["intake"] = "completed"
                self.store.save_job(job)
                
            # Step 2: Analyze
            check_cancellation()
            if job.steps.get("analyze", "pending") == "pending":
                job.current_step = "analyze"
                self.store.save_job(job)
                logger.info("--- Step 2: Analyze ---")
                
                dest_video = self._get_dest_video(work_dir)
                metadata = self.analyzer.analyze(dest_video)
                write_json(work_dir / "metadata.json", metadata)
                
                job.steps["analyze"] = "completed"
                self.store.save_job(job)
                
            # Step 3: Extract Audio
            check_cancellation()
            if job.steps.get("extract_audio", "pending") == "pending":
                job.current_step = "extract_audio"
                self.store.save_job(job)
                logger.info("--- Step 3: Extract Audio ---")
                
                dest_video = self._get_dest_video(work_dir)
                self.extractor.extract(dest_video, work_dir / "audio.wav")
                
                job.steps["extract_audio"] = "completed"
                self.store.save_job(job)
                
            # Step 4: Transcribe / Import SRT
            check_cancellation()
            if job.steps.get("transcribe", "pending") == "pending":
                job.current_step = "transcribe"
                self.store.save_job(job)
                logger.info("--- Step 4: Transcribe / Import SRT ---")
                
                input_srt = work_dir / "input.srt"
                if input_srt.exists():
                    logger.info("Loading existing sidecar SRT...")
                    subs = pysrt.open(str(input_srt), encoding="utf-8")
                    segments = []
                    for idx, sub in enumerate(subs):
                        segments.append(Segment(
                            id=idx + 1,
                            start_ms=sub.start.ordinal,
                            end_ms=sub.end.ordinal,
                            source_text=sub.text,
                            status="pending"
                        ))
                    self.store.save_transcript(job_id, segments)
                    job.steps["transcribe"] = "completed"
                    self.store.save_job(job)
                else:
                    # No sidecar SRT, try auto-transcription with faster-whisper if installed
                    try:
                        from faster_whisper import WhisperModel
                        logger.info("No sidecar SRT found. Initiating Whisper auto-transcription...")
                        audio_path = work_dir / "audio.wav"
                        # base model is fast and works reasonably on CPU
                        model = WhisperModel("base", device="cpu", compute_type="float32")
                        segments_iter, info = model.transcribe(
                            str(audio_path),
                            beam_size=5,
                            vad_filter=True,
                            condition_on_previous_text=False
                        )
                        segments = []
                        for idx, s in enumerate(segments_iter):
                            segments.append(Segment(
                                id=idx + 1,
                                start_ms=int(s.start * 1000),
                                end_ms=int(s.end * 1000),
                                source_text=s.text.strip(),
                                status="pending"
                            ))
                        self.store.save_transcript(job_id, segments)
                        
                        # Generate sidecar input.srt in work dir
                        subs = pysrt.SubRipFile()
                        for s in segments:
                            sub = pysrt.SubRipItem(
                                index=s.id,
                                start=pysrt.SubRipTime(milliseconds=s.start_ms),
                                end=pysrt.SubRipTime(milliseconds=s.end_ms),
                                text=s.source_text
                            )
                            subs.append(sub)
                        subs.save(str(input_srt), encoding="utf-8")
                        
                        job.steps["transcribe"] = "completed"
                        self.store.save_job(job)
                    except ImportError:
                        raise AutoToolError(
                            "No sidecar SRT file found and faster-whisper is not installed. "
                            "Please place an SRT file with the same name next to the input video."
                        )
                    except Exception as e:
                        raise AutoToolError(f"Auto-transcription failed: {e}")
                        
            # Step 5: Translate
            check_cancellation()
            if job.steps.get("translate", "pending") == "pending":
                job.current_step = "translate"
                self.store.save_job(job)
                logger.info("--- Step 5: Translate ---")
                
                segments = self.store.load_transcript(job_id)
                if not segments:
                    logger.warning("No transcript segments found to translate.")
                else:
                    segments = self.translator.translate(segments, tone)
                    
                self.store.save_translated(job_id, segments)
                job.steps["translate"] = "completed"
                self.store.save_job(job)
                
            # Step 6: TTS (Voiceover Generation)
            check_cancellation()
            if job.steps.get("tts", "pending") == "pending":
                job.current_step = "tts"
                self.store.save_job(job)
                logger.info("--- Step 6: TTS ---")
                
                segments = self.store.load_translated(job_id)
                if segments:
                    segments = await self.tts_service.generate_voiceovers(
                        segments=segments,
                        work_dir=work_dir,
                        voice=voice,
                        rate=rate,
                        pitch=pitch
                    )
                    self.store.save_translated(job_id, segments)
                    
                job.steps["tts"] = "completed"
                self.store.save_job(job)
                
            # Step 7: Mix Audio
            check_cancellation()
            if job.steps.get("mix_audio", "pending") == "pending":
                job.current_step = "mix_audio"
                self.store.save_job(job)
                logger.info("--- Step 7: Mix Audio ---")
                
                segments = self.store.load_translated(job_id)
                
                # Resolve BGM path
                bgm_path = None
                if bgm_name:
                    # Map abstract BGM names to actual files in examples/music
                    bgm_mapping = {
                        "dramatic_loop": "leberch-soft-piano-501446",
                        "funny_loop": "lightbeatsmusic-joyful-rhythm-walk-funk-513936",
                        "sad_loop": "leberch-soft-piano-501446"
                    }
                    if bgm_name in bgm_mapping:
                        logger.info(f"Mapping BGM name '{bgm_name}' to existing file: '{bgm_mapping[bgm_name]}'")
                        bgm_name = bgm_mapping[bgm_name]

                    music_dir = Path(settings.default_music_folder)
                    for ext in [".mp3", ".wav", ".m4a"]:
                        test_path = music_dir / f"{bgm_name}{ext}"
                        if test_path.exists():
                            bgm_path = test_path
                            break
                    if not bgm_path:
                        test_path = Path(bgm_name)
                        if test_path.exists():
                            bgm_path = test_path
                            
                # Load video duration from metadata if available
                metadata_path = work_dir / "metadata.json"
                video_duration_ms = None
                if metadata_path.exists():
                    try:
                        with open(metadata_path, "r", encoding="utf-8") as f:
                            metadata = json.load(f)
                            if "duration" in metadata:
                                video_duration_ms = int(metadata["duration"] * 1000)
                    except Exception as e:
                        logger.warning(f"Failed to read metadata.json for duration: {e}")

                self.mixer.mix(
                    original_audio_path=work_dir / "audio.wav",
                    segments=segments,
                    output_mixed_path=work_dir / "mixed_audio.wav",
                    bgm_path=bgm_path,
                    original_volume=settings.original_volume,
                    tts_volume=settings.tts_volume,
                    bgm_volume=settings.bgm_volume,
                    video_duration_ms=video_duration_ms
                )
                
                job.steps["mix_audio"] = "completed"
                self.store.save_job(job)
                
            # Step 8: Render Video
            check_cancellation()
            if job.steps.get("render", "pending") == "pending":
                job.current_step = "render"
                self.store.save_job(job)
                logger.info("--- Step 8: Render ---")
                
                segments = self.store.load_translated(job_id)
                
                # Write output.srt for burning into video
                output_srt = work_dir / "output.srt"
                subs = pysrt.SubRipFile()
                for s in segments:
                    sub = pysrt.SubRipItem(
                        index=s.id,
                        start=pysrt.SubRipTime(milliseconds=s.start_ms),
                        end=pysrt.SubRipTime(milliseconds=s.end_ms),
                        text=s.translated_text
                    )
                    subs.append(sub)
                subs.save(str(output_srt), encoding="utf-8")
                
                # Load metadata
                with open(work_dir / "metadata.json", "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                    
                dest_video = self._get_dest_video(work_dir)
                final_video = output_dir / "final.mp4"
                
                self.render_service.render(
                    video_path=dest_video,
                    audio_path=work_dir / "mixed_audio.wav",
                    srt_path=output_srt,
                    output_path=final_video,
                    metadata=metadata,
                    logo_path=logo_path,
                    mask_subtitle=mask_subtitle
                )
                
                job.steps["render"] = "completed"
                self.store.save_job(job)
                
            # Step 9: Metadata & Post Captioning
            check_cancellation()
            if job.steps.get("metadata", "pending") == "pending":
                job.current_step = "metadata"
                self.store.save_job(job)
                logger.info("--- Step 9: Metadata & Captioning ---")
                
                segments = self.store.load_translated(job_id)
                
                # Default fallback values
                title = "Video dịch & lồng tiếng bởi AutoTool"
                hashtags = "#autotool #dichphim #reviewphim"
                
                # Try calling Gemini to generate highly catchy titles and hashtags contextually
                if self.translator.client is not None:
                    try:
                        summary_prompt = (
                            "Bạn là chuyên gia sáng tạo nội dung mạng xã hội. Hãy viết 1 tiêu đề ngắn cực kỳ giật gân, "
                            "kịch tính, kích thích người xem click (phong cách video ngắn) cho nội dung đối thoại bên dưới "
                            "và đề xuất 3-5 hashtag liên quan bằng tiếng Việt. Trả về đúng định dạng:\n"
                            "Tiêu đề\n"
                            "#hashtag1 #hashtag2...\n\n"
                            "Nội dung thoại:\n"
                        )
                        summary_prompt += "\n".join([s.translated_text for s in segments[:12]])
                        
                        response = self.translator.client.models.generate_content(
                            model='gemini-2.5-flash',
                            contents=summary_prompt
                        )
                        lines = [line.strip() for line in response.text.strip().split("\n") if line.strip()]
                        if lines:
                            title = lines[0]
                        if len(lines) > 1:
                            hashtags = " ".join(lines[1:])
                    except Exception as e:
                        logger.warning(f"Failed to generate custom AI captions: {e}")
                        
                # Save to caption.txt
                caption_file = output_dir / "caption.txt"
                with open(caption_file, "w", encoding="utf-8") as f:
                    f.write(f"{title}\n\n{hashtags}\n")
                    
                job.steps["metadata"] = "completed"
                job.status = "completed"
                self.store.save_job(job)
                logger.info("--- Pipeline Completed Successfully! ---")
                
        except Exception as e:
            logger.error(f"Pipeline crashed at step '{job.current_step}': {e}")
            job.status = "failed"
            job.errors.append(str(e))
            self.store.save_job(job)
            raise e
        finally:
            if 'file_handler' in locals():
                logger.removeHandler(file_handler)
                file_handler.close()
