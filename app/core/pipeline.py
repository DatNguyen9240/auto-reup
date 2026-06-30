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

PROJECT_ROOT = Path(__file__).resolve().parents[2]

import logging

def _find_chrome_profile_for_email(email: str) -> Optional[str]:
    chrome_user_data = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    if not chrome_user_data.exists():
        return None
    for profile_dir in chrome_user_data.iterdir():
        if not profile_dir.is_dir() or (profile_dir.name != "Default" and not profile_dir.name.startswith("Profile ")):
            continue
        preferences = profile_dir / "Preferences"
        if not preferences.exists():
            continue
        try:
            if email.lower() in preferences.read_text(encoding="utf-8", errors="ignore").lower():
                return profile_dir.name
        except Exception:
            continue
    return None

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

    def _log_segment_progress(self, action: str, index: int, total: int, segment: Segment, text: str = ""):
        preview = (text or segment.source_text or "").replace("\n", " ").strip()
        if len(preview) > 90:
            preview = preview[:87] + "..."
        logger.info(f"{action} [{index}/{total}] segment #{segment.id}: {preview}")

    def _get_dest_video(self, work_dir: Path) -> Path:
        """Safely resolves the input video path in the work directory."""
        matches = list(work_dir.glob("input.*"))
        if not matches:
            raise AutoToolError(f"No input video file found in work directory: {work_dir}")
        return matches[0]

    def _resolve_asset_path(self, logo: Optional[str], channel_id: Optional[str] = None) -> Optional[Path]:
        if not logo:
            return None
            
        # 1. Global overlay
        overlay_path = PROJECT_ROOT / "examples" / "overlay" / logo
        if overlay_path.exists() and overlay_path.is_file():
            return overlay_path
            
        # 2. Absolute path
        logo_path = Path(logo)
        if logo_path.is_absolute() and logo_path.exists():
            return logo_path
            
        # 3. Relative to project root
        proj_path = PROJECT_ROOT / logo
        if proj_path.exists() and proj_path.is_file():
            return proj_path
            
        # 4. Relative to channel folder if channel_id is provided
        if channel_id:
            try:
                channels_file = self.projects_dir / "channels.json"
                if channels_file.exists():
                    with open(channels_file, "r", encoding="utf-8") as f:
                        channels = json.load(f)
                    chan = next((c for c in channels if c.get("id") == channel_id), None)
                    if chan:
                        chan_name = chan.get("name")
                        chan_path = chan.get("path")
                        
                        # Resolve channel path
                        if not chan_path or not chan_path.strip():
                            chan_dir = PROJECT_ROOT / "outputs" / chan_name
                        else:
                            p = Path(chan_path.strip())
                            chan_dir = p if p.is_absolute() else PROJECT_ROOT / p
                            
                        chan_logo_path = chan_dir / logo
                        if chan_logo_path.exists() and chan_logo_path.is_file():
                            return chan_logo_path
                            
                        root_logo_path = chan_dir / Path(logo).name
                        if root_logo_path.exists() and root_logo_path.is_file():
                            return root_logo_path
            except Exception as e:
                logger.error(f"Failed resolving channel-specific logo in pipeline: {e}")
        return None

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
        mask_subtitle: bool = True,
        tts_enabled: bool = True,
        subtitles_enabled: bool = True,
        subtitle_cover_mode: str = "text_box_only",
        subtitle_bg_opacity: float = 0.42,
        subtitle_mask_padding_x: int = 20,
        subtitle_mask_padding_y: int = 12,
        ocr_sample_interval_sec: float = 0.75,
        ocr_crop_bottom_ratio: float = 0.45,
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

        job.status = "processing"
        job.steps.setdefault("subtitle_layout", "pending")
        self.store.save_job(job)
        
        job_dir = self.projects_dir / job_id
        work_dir = job_dir / "work"
        output_dir = job_dir / "output"
        
        ensure_dir(work_dir)
        ensure_dir(output_dir)
        
        try:
            import logging
            log_file = job_dir / "run.log"
            file_handler = FlushingFileHandler(str(log_file), mode="w", encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.INFO)
            logger.setLevel(logging.INFO)
            file_handler.setLevel(logging.INFO)
            root_logger.addHandler(file_handler)
            logger.info(f"=== Starting job {job_id} ===")
            
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
                    
                    from app.services.downloader import normalize_douyin_url
                    normalized_url = normalize_douyin_url(job.input_path) if is_douyin else job.input_path
                    
                    def run_ytdl():
                        attempts = []
                        project_root = Path(__file__).resolve().parents[2]
                        cookie_file = project_root / "cookies.txt"
                        if cookie_file.exists() and cookie_file.stat().st_size > 100:
                            logger.info(f"Adding cookies.txt to yt-dlp: {cookie_file}")
                            attempts.append(("cookies.txt", {'cookiefile': str(cookie_file)}))
                        
                        attempts.extend([
                            ("Chrome cookies", {'cookiesfrombrowser': ('chrome',)}),
                            ("Edge cookies", {'cookiesfrombrowser': ('edge',)}),
                            ("no cookies", {})
                        ])
                        
                        last_error = None
                        for label, extra_opts in attempts:
                            try:
                                logger.info(f"yt-dlp download attempt: {label}")
                                opts = dict(ydl_opts)
                                opts.update(extra_opts)
                                with yt_dlp.YoutubeDL(opts) as ydl:
                                    info_dict = ydl.extract_info(normalized_url, download=True)
                                    return {
                                        "title": info_dict.get("title") or job_id,
                                        "duration": info_dict.get("duration") or 0,
                                        "thumbnail": info_dict.get("thumbnail") or "",
                                        "play_addr": info_dict.get("url") or "",
                                        "uploader": info_dict.get("uploader") or "",
                                    }
                            except Exception as e:
                                last_error = e
                                logger.warning(f"yt-dlp download failed using {label}: {e}")
                        raise last_error

                    try:
                        logger.info("Attempting download using yt-dlp...")
                        info = await asyncio.get_event_loop().run_in_executor(None, run_ytdl)
                        logger.info("yt-dlp download completed successfully.")
                    except Exception as ytdl_err:
                        if is_douyin:
                            logger.info("yt-dlp download failed. Falling back to generic Douyin Playwright downloader...")
                            from app.services.downloader import PlaywrightDownloaderService
                            downloader = PlaywrightDownloaderService()
                            try:
                                info = await downloader.download_video_async(job.input_path, dest_video)
                                logger.info("Generic Douyin Playwright downloader succeeded.")
                            except Exception as playwright_err:
                                logger.error(f"Douyin Playwright downloader failed: {playwright_err}")
                                raise AutoToolError(f"Failed to download video from URL: {playwright_err}")
                        else:
                            raise AutoToolError(f"Failed to download video from URL: {ytdl_err}")
                        
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
                
                job.input_width = metadata.get("input_width", 0)
                job.input_height = metadata.get("input_height", 0)
                job.input_aspect_ratio = metadata.get("input_aspect_ratio", 1.0)
                job.input_aspect_type = metadata.get("input_aspect_type", "vertical")
                
                # Initialize default selected outputs if not custom configured
                snapshot = job.config_snapshot or {}
                if "selected_outputs" not in snapshot or not snapshot["selected_outputs"]:
                    snapshot["selected_outputs"] = ["fb_reels"]
                    job.config_snapshot = snapshot
                    
                # Initialize outputs status structure
                from datetime import datetime
                for out in snapshot["selected_outputs"]:
                    if out not in job.outputs:
                        job.outputs[out] = {
                            "output_type": out,
                            "file_path": "",
                            "width": 1920 if out == "yt_video" else 1080,
                            "height": 1080 if out == "yt_video" else 1920,
                            "duration": metadata.get("duration", 0),
                            "render_status": "pending",
                            "upload_status": "pending",
                            "created_at": datetime.utcnow().isoformat()
                        }
                
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
                    logger.info(f"Found {len(subs)} subtitle lines in sidecar SRT.")
                    segments = []
                    for idx, sub in enumerate(subs):
                        segment = Segment(
                            id=idx + 1,
                            start_ms=sub.start.ordinal,
                            end_ms=sub.end.ordinal,
                            source_text=sub.text,
                            status="pending"
                        )
                        segments.append(segment)
                        self._log_segment_progress("Recognized", idx + 1, len(subs), segment)
                    self.store.save_transcript(job_id, segments)
                    logger.info(f"Step 4 completed: recognized/imported {len(segments)} dialogue lines.")
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
                            segment = Segment(
                                id=idx + 1,
                                start_ms=int(s.start * 1000),
                                end_ms=int(s.end * 1000),
                                source_text=s.text.strip(),
                                status="pending"
                            )
                            segments.append(segment)
                            self._log_segment_progress("Recognized", idx + 1, idx + 1, segment)
                        self.store.save_transcript(job_id, segments)
                        logger.info(f"Step 4 completed: recognized {len(segments)} dialogue lines.")
                        
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
                    logger.info(f"Step 5 starting: translating {len(segments)} dialogue lines.")
                    segments = self.translator.translate(segments, tone)
                    for idx, segment in enumerate(segments, start=1):
                        self._log_segment_progress("Translated", idx, len(segments), segment, segment.translated_text)
                    logger.info(f"Step 5 completed: translated {len(segments)} dialogue lines.")
                    
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
                if not tts_enabled:
                    logger.info("TTS disabled for this job; keeping original audio/BGM only.")
                    for segment in segments:
                        segment.tts_path = None
                    self.store.save_translated(job_id, segments)
                elif segments:
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
            if subtitles_enabled and job.steps.get("subtitle_layout", "pending") == "pending":
                job.current_step = "subtitle_layout"
                job.status = "waiting_for_subtitle_layout"
                self.store.save_job(job)
                logger.info("--- Step 8: Subtitle Layout ---")
                logger.info("Basic processing completed. Waiting for user to choose subtitle position before final render.")
                return

            if job.steps.get("render", "pending") == "pending":
                job.current_step = "render"
                job.steps["subtitle_layout"] = "completed"
                job.status = "rendering"
                self.store.save_job(job)
                logger.info("--- Step 9: Render (Multi-Format Loop) ---")
                
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
                snapshot = job.config_snapshot or {}
                selected_outputs = snapshot.get("selected_outputs") or []
                if not selected_outputs:
                    # Fallback to standard vertical render
                    selected_outputs = ["fb_reels"]
                
                logger.info(f"Selected outputs to render: {selected_outputs}")
                
                for out in selected_outputs:
                    logger.info(f"Starting render for format: {out}")
                    if out not in job.outputs:
                        from datetime import datetime
                        job.outputs[out] = {
                            "output_type": out,
                            "file_path": "",
                            "width": 1920 if out == "yt_video" else 1080,
                            "height": 1080 if out == "yt_video" else 1920,
                            "duration": metadata.get("duration", 0),
                            "render_status": "pending",
                            "upload_status": "pending",
                            "created_at": datetime.utcnow().isoformat()
                        }
                    
                    job.outputs[out]["render_status"] = "rendering"
                    self.store.save_job(job)
                    
                    # Define format target specs
                    if out == "yt_video":
                        w_out, h_out = 1920, 1080
                        filename = "yt_video_16x9.mp4"
                    elif out == "yt_shorts":
                        w_out, h_out = 1080, 1920
                        filename = "yt_shorts_9x16.mp4"
                    else:
                        w_out, h_out = 1080, 1920
                        filename = "fb_reels_9x16.mp4"
                        
                    reframe_mode = snapshot.get(f"{out}_reframe_mode", "keep_original")
                    crop_layout = snapshot.get(f"{out}_crop")
                    
                    asset_path = None
                    asset = snapshot.get("asset")
                    if asset:
                        asset_path = self._resolve_asset_path(asset, snapshot.get("channel_id"))
                            
                    final_video = output_dir / filename
                    
                    try:
                        self.render_service.render(
                            video_path=dest_video,
                            audio_path=work_dir / "mixed_audio.wav",
                            srt_path=output_srt,
                            output_path=final_video,
                            metadata=metadata,
                            logo_path=logo_path,
                            mask_subtitle=mask_subtitle,
                            render_subtitles=subtitles_enabled,
                            subtitle_layout=snapshot.get("subtitle_layout"),
                            subtitle_cover_mode=subtitle_cover_mode,
                            subtitle_bg_opacity=subtitle_bg_opacity,
                            subtitle_mask_padding_x=subtitle_mask_padding_x,
                            subtitle_mask_padding_y=subtitle_mask_padding_y,
                            ocr_sample_interval_sec=ocr_sample_interval_sec,
                            ocr_crop_bottom_ratio=ocr_crop_bottom_ratio,
                            debug_dir=job_dir / "debug" / "subtitle_detection",
                            w_out=w_out,
                            h_out=h_out,
                            reframe_mode=reframe_mode,
                            crop_layout=crop_layout,
                            logo_position=snapshot.get("logo_position", "top_center"),
                            logo_layout=snapshot.get("logo_layout"),
                            asset_path=asset_path,
                            asset_layout=snapshot.get("asset_layout"),
                            blur_masks=snapshot.get("blur_masks", [])
                        )
                        
                        # Copy completed render to the centralized Completed directory
                        completed_dir = PROJECT_ROOT / "outputs" / "Completed"
                        completed_dir.mkdir(parents=True, exist_ok=True)
                        dest_completed = completed_dir / f"{job_id}_{filename}"
                        shutil.copy2(final_video, dest_completed)
                        
                        job.outputs[out]["file_path"] = str(final_video)
                        job.outputs[out]["render_status"] = "completed"
                        
                        # Set default job.output_path to the first rendered output for safety
                        if not job.output_path:
                            job.output_path = str(final_video)
                            
                        logger.info(f"Successfully rendered and centralized format: {out}")
                        
                    except Exception as render_err:
                        logger.error(f"Render failed for format {out}: {render_err}")
                        job.outputs[out]["render_status"] = "failed"
                        raise render_err
                        
                job.steps["render"] = "completed"
                self.store.save_job(job)
                
            # Step 9: Metadata & Post Captioning
            check_cancellation()
            if job.steps.get("metadata", "pending") == "pending":
                job.current_step = "metadata"
                self.store.save_job(job)
                logger.info("--- Step 10: Metadata & Captioning ---")
                
                segments = self.store.load_translated(job_id)
                
                # Default fallback values
                facebook_caption = "Video Việt hóa & lồng tiếng tự động bởi AutoTool"
                facebook_hashtags = "#autotool #dichphim #reviewphim"
                youtube_shorts_title = "Video dịch tự động #shorts"
                youtube_shorts_description = "Video dịch & lồng tiếng bởi AutoTool Studio #shorts"
                youtube_shorts_tags = "autotool, dịch phim, review phim"
                youtube_video_title = "Video dịch & lồng tiếng tự động bởi AutoTool Studio"
                youtube_video_description = "Video dịch & lồng tiếng tự động từ tiếng Trung sang tiếng Việt bằng AutoTool."
                youtube_video_tags = "autotool, dịch phim, review phim"
                
                # Try calling Gemini to generate highly catchy titles and hashtags contextually
                if self.translator.client is not None:
                    try:
                        from pydantic import BaseModel
                        class AIProgressMetadata(BaseModel):
                            facebook_caption: str
                            facebook_hashtags: str
                            youtube_shorts_title: str
                            youtube_shorts_description: str
                            youtube_shorts_tags: str
                            youtube_video_title: str
                            youtube_video_description: str
                            youtube_video_tags: str

                        summary_prompt = (
                            "Bạn là chuyên gia sáng tạo nội dung mạng xã hội đa kênh. Hãy dựa vào nội dung đối thoại bên dưới "
                            "để viết các captions, tiêu đề giật gân chuẩn SEO và các hashtags phù hợp cho từng nền tảng: "
                            "Facebook Reels, YouTube Shorts, và YouTube Video thường. Trả về định dạng JSON đúng schema được cung cấp.\n\n"
                            "Nội dung thoại:\n"
                        )
                        summary_prompt += "\n".join([s.translated_text for s in segments[:15]])
                        
                        response = self.translator.generate_content(
                            prompt=summary_prompt,
                            model='gemini-2.5-flash',
                            mime_type='application/json',
                            schema=AIProgressMetadata
                        )
                        
                        ai_data = json.loads(response.text)
                        facebook_caption = ai_data.get("facebook_caption", facebook_caption)
                        facebook_hashtags = ai_data.get("facebook_hashtags", facebook_hashtags)
                        youtube_shorts_title = ai_data.get("youtube_shorts_title", youtube_shorts_title)
                        youtube_shorts_description = ai_data.get("youtube_shorts_description", youtube_shorts_description)
                        youtube_shorts_tags = ai_data.get("youtube_shorts_tags", youtube_shorts_tags)
                        youtube_video_title = ai_data.get("youtube_video_title", youtube_video_title)
                        youtube_video_description = ai_data.get("youtube_video_description", youtube_video_description)
                        youtube_video_tags = ai_data.get("youtube_video_tags", youtube_video_tags)
                        
                        # Save to job config snapshot so client can display it
                        snapshot = job.config_snapshot or {}
                        snapshot["facebook_caption"] = facebook_caption
                        snapshot["facebook_hashtags"] = facebook_hashtags
                        snapshot["youtube_shorts_title"] = youtube_shorts_title
                        snapshot["youtube_shorts_description"] = youtube_shorts_description
                        snapshot["youtube_shorts_tags"] = youtube_shorts_tags
                        snapshot["youtube_video_title"] = youtube_video_title
                        snapshot["youtube_video_description"] = youtube_video_description
                        snapshot["youtube_video_tags"] = youtube_video_tags
                        job.config_snapshot = snapshot
                        
                    except Exception as e:
                        logger.warning(f"Failed to generate custom AI captions: {e}")
                        
                # Save to caption.txt (Keep legacy caption format for compatibility)
                caption_file = output_dir / "caption.txt"
                with open(caption_file, "w", encoding="utf-8") as f:
                    f.write(f"Facebook Reels Caption:\n{facebook_caption} {facebook_hashtags}\n\n")
                    f.write(f"YouTube Shorts Title:\n{youtube_shorts_title}\n\n")
                    f.write(f"YouTube Video Title:\n{youtube_video_title}\n")
                    
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
                logging.getLogger().removeHandler(file_handler)
                file_handler.close()
