import os
import shutil
import json
import asyncio
from pathlib import Path
from typing import List, Optional
import pysrt

from app.config import settings, EMOTION_PRESETS

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
from app.utils.logger import get_logger, JobLogFilter
from app.utils.file_utils import ensure_dir, write_json

logger = get_logger("Pipeline")

import threading
_whisper_model = None
_whisper_model_device = None
_whisper_force_cpu = False
_whisper_model_lock = threading.Lock()

def _get_whisper_model(force_cpu: bool = False):
    global _whisper_model, _whisper_model_device, _whisper_force_cpu
    with _whisper_model_lock:
        if force_cpu:
            _whisper_force_cpu = True
            if _whisper_model_device != "cpu":
                _whisper_model = None  # Force recreation on CPU
                _whisper_model_device = None
            
        if _whisper_model is None:
            import os
            # Disable HF symlinks on Windows to avoid privilege error (WinError 1314)
            os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
            
            from faster_whisper import WhisperModel
            from app.config import settings
            model_size = settings.whisper_model_size or "base"
            
            use_cuda = not force_cpu and not _whisper_force_cpu
            if use_cuda:
                try:
                    logger.info(f"Attempting to initialize WhisperModel ('{model_size}') on GPU (CUDA)...")
                    _whisper_model = WhisperModel(model_size, device="cuda", compute_type="float16")
                    _whisper_model_device = "cuda"
                    logger.info(f"Successfully initialized WhisperModel ('{model_size}') on GPU (CUDA).")
                except Exception as e:
                    logger.info(f"Failed to initialize WhisperModel ('{model_size}') on GPU (CUDA): {e}. Falling back to CPU...")
                    use_cuda = False
                    
            if not use_cuda:
                import multiprocessing
                # Use half of physical CPU cores (cap at 4 to prevent thrashing but keep fast)
                cpu_cores = max(1, min(4, multiprocessing.cpu_count() // 2))
                logger.info(f"Initializing WhisperModel on CPU with {cpu_cores} threads...")
                _whisper_model = WhisperModel(
                    model_size, 
                    device="cpu", 
                    compute_type="int8" if model_size != "large-v3" else "float32", # Use int8 quantization on CPU for 3x speedup!
                    cpu_threads=cpu_cores
                )
                _whisper_model_device = "cpu"
        return _whisper_model

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

    def _resolve_export_dir(self, job: Job) -> Path:
        job_id = job.job_id
        snapshot = job.config_snapshot or {}
        channel_id = snapshot.get("channel_id") or job.channel_id
        
        if channel_id and channel_id != "default":
            channels_file = self.projects_dir / "channels.json"
            if channels_file.exists():
                try:
                    with open(channels_file, "r", encoding="utf-8") as f:
                        channels = json.load(f)
                    chan = next((c for c in channels if c.get("id") == channel_id), None)
                    if chan:
                        chan_name = chan.get("name", "UnknownChannel")
                        chan_path = chan.get("path", "").strip()
                        if chan_path:
                            p = Path(chan_path)
                            if not p.is_absolute():
                                p = PROJECT_ROOT / p
                            return p / job_id
                        else:
                            return PROJECT_ROOT / "outputs" / chan_name / job_id
                except Exception as e:
                    logger.error(f"Failed to resolve channel export path: {e}")
                    
        # Fallback to default completed path
        if settings.default_export_path:
            return Path(settings.default_export_path) / job_id
        return PROJECT_ROOT / "outputs" / "Completed" / job_id

    def _get_dest_video(self, work_dir: Path) -> Path:
        """Safely resolves the input video path in the work directory."""
        matches = list(work_dir.glob("input.*"))
        if not matches:
            raise AutoToolError(f"No input video file found in work directory: {work_dir}")
        return matches[0]

    def _extract_text_segments_via_ocr(self, video_path: Path, work_dir: Path, duration: float) -> List[Segment]:
        """Chụp khung hình mỗi 1 giây, chạy OCR để lấy text và gộp các khung hình trùng chữ thành Segment."""
        logger.info("Bắt đầu trích xuất phụ đề bằng OCR từ video (chế độ không lời/dùng chữ)...")
        
        # 1. Tạo thư mục tạm để lưu frames
        ocr_frames_dir = work_dir / "ocr_frames"
        ocr_frames_dir.mkdir(parents=True, exist_ok=True)
        
        # 2. Dùng ffmpeg xuất khung hình mỗi 1 giây
        pattern = ocr_frames_dir / "frame_%03d.jpg"
        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-i", str(video_path),
            "-vf", "fps=1",
            "-q:v", "3",
            str(pattern)
        ]
        try:
            import subprocess
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except Exception as e:
            logger.warning(f"Thất bại khi xuất khung hình cho OCR: {e}")
            return []
            
        frame_files = sorted(ocr_frames_dir.glob("frame_*.jpg"))
        if not frame_files:
            logger.warning("Không trích xuất được khung hình nào.")
            return []
            
        # 3. Khởi tạo OCR engine
        reader = None
        try:
            import easyocr
            reader = easyocr.Reader(["ch_sim", "en", "vi"], gpu=False, verbose=False)
            logger.info("Đã khởi tạo EasyOCR để nhận diện chữ trên màn hình.")
        except Exception as e:
            logger.warning(f"Không thể khởi tạo EasyOCR: {e}. Thử dùng PaddleOCR...")
            try:
                from paddleocr import PaddleOCR
                reader = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)
                logger.info("Đã khởi tạo PaddleOCR để nhận diện chữ trên màn hình.")
            except Exception as e2:
                logger.warning(f"Không tìm thấy thư viện OCR (EasyOCR/PaddleOCR): {e2}.")
                
        # 4. Duyệt qua từng khung hình và chạy OCR
        raw_detections = []
        
        for idx, frame_path in enumerate(frame_files, start=1):
            time_sec = float(idx - 1)
            text = ""
            
            if reader is not None:
                try:
                    if hasattr(reader, "readtext"):
                        import cv2
                        img = cv2.imread(str(frame_path))
                        h, w = img.shape[:2]
                        crop = img[int(h*0.55):, :]
                        results = reader.readtext(crop)
                        texts = [r[1].strip() for r in results if r[2] > 0.35]
                        text = " ".join(texts).strip()
                    else:
                        import cv2
                        img = cv2.imread(str(frame_path))
                        h, w = img.shape[:2]
                        crop = img[int(h*0.55):, :]
                        result = reader.ocr(crop, cls=False)
                        texts = []
                        for line in result or []:
                            for item in line or []:
                                txt = item[1][0].strip()
                                score = float(item[1][1])
                                if score > 0.35:
                                    texts.append(txt)
                        text = " ".join(texts).strip()
                except Exception as ocr_err:
                    logger.debug(f"Lỗi OCR tại khung hình {frame_path.name}: {ocr_err}")
                    
            if text:
                raw_detections.append((time_sec, text))
                
        # Dọn dẹp
        import shutil
        try:
            shutil.rmtree(ocr_frames_dir)
        except Exception:
            pass
            
        if not raw_detections:
            logger.info("OCR không tìm thấy chữ nào trên màn hình.")
            return []
            
        # 5. Gom các khung hình có chữ giống nhau liên tiếp thành Segment
        def is_similar(t1: str, t2: str) -> bool:
            w1 = set(t1.lower().split())
            w2 = set(t2.lower().split())
            if not w1 or not w2:
                return False
            intersection = w1.intersection(w2)
            return (len(intersection) / min(len(w1), len(w2))) >= 0.5
            
        segments = []
        current_segment = None
        seg_id = 1
        
        for time_sec, text in raw_detections:
            time_ms = int(time_sec * 1000)
            
            if current_segment is None:
                current_segment = {
                    "id": seg_id,
                    "start_ms": time_ms,
                    "end_ms": time_ms + 1000,
                    "text": text
                }
            else:
                if is_similar(current_segment["text"], text) and (time_ms - current_segment["end_ms"] <= 2000):
                    current_segment["end_ms"] = time_ms + 1000
                    if len(text) > len(current_segment["text"]):
                        current_segment["text"] = text
                else:
                    segments.append(Segment(
                        id=current_segment["id"],
                        start_ms=current_segment["start_ms"],
                        end_ms=current_segment["end_ms"],
                        source_text=current_segment["text"],
                        status="pending"
                    ))
                    seg_id += 1
                    current_segment = {
                        "id": seg_id,
                        "start_ms": time_ms,
                        "end_ms": time_ms + 1000,
                        "text": text
                    }
                    
        if current_segment is not None:
            segments.append(Segment(
                id=current_segment["id"],
                start_ms=current_segment["start_ms"],
                end_ms=current_segment["end_ms"],
                source_text=current_segment["text"],
                status="pending"
            ))
            
    def _resolve_tts_voice(self, target_language: str, target_locale: Optional[str], current_voice: Optional[str]) -> str:
        """Đảm bảo giọng đọc (Voice TTS) phù hợp với ngôn ngữ đích dịch thuật."""
        lang_prefix = target_language.split("-")[0].lower()
        if current_voice and current_voice.lower().startswith(lang_prefix):
            return current_voice
            
        mappings = {
            "vi": "vi-VN-HoaiMyNeural",
            "en": "en-US-EmmaNeural",
            "es": {
                "es-MX": "es-MX-DaliaNeural",
                "es-ES": "es-ES-ElviraNeural",
                "default": "es-MX-DaliaNeural"
            },
            "pt": {
                "pt-BR": "pt-BR-FranciscaNeural",
                "pt-PT": "pt-PT-RaquelNeural",
                "default": "pt-BR-FranciscaNeural"
            },
            "ru": "ru-RU-SvetlanaNeural",
            "th": "th-TH-AcharaNeural",
            "id": "id-ID-GadisNeural",
            "ja": "ja-JP-NanamiNeural",
            "ko": "ko-KR-SunHiNeural"
        }
        
        if lang_prefix in mappings:
            val = mappings[lang_prefix]
            if isinstance(val, dict):
                loc = target_locale or "default"
                return val.get(loc) or val.get("default")
            return val
            
        return "en-US-EmmaNeural"

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
        from app.utils.logger import set_current_job_id
        set_current_job_id(job_id)
        job = self.store.load_job(job_id)
        if not job:
            raise AutoToolError(f"Job {job_id} not found.")

        def check_cancellation():
            curr = self.store.load_job(job_id)
            if not curr or curr.status == "failed" or curr.status == "cancelled":
                raise AutoToolError("Job bị ngắt bởi người dùng.")

        # Apply Emotion Preset mapping if defaults are used and tone has a preset
        
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
            file_handler.setLevel(logging.INFO)
            # Add JobLogFilter to prevent logs from other concurrently running jobs from interleaving
            file_handler.addFilter(JobLogFilter(job_id))
            
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.INFO)
            logger.setLevel(logging.INFO)
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
                    is_bilibili = "bilibili.com" in job.input_path or "b23.tv" in job.input_path
                    
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
                        from app.utils.logger import wrap_with_job_context
                        info = await asyncio.get_event_loop().run_in_executor(None, wrap_with_job_context(job_id, run_ytdl))
                        logger.info("yt-dlp download completed successfully.")
                    except Exception as ytdl_err:
                        if is_douyin:
                            logger.info("yt-dlp download failed. Falling back to generic Douyin Playwright downloader...")
                            from app.services.downloader import PlaywrightDownloaderService
                            downloader = PlaywrightDownloaderService()
                            try:
                                info = await downloader.download_video_async(job.input_path, dest_video, job_id)
                                logger.info("Generic Douyin Playwright downloader succeeded.")
                            except Exception as playwright_err:
                                logger.error(f"Douyin Playwright downloader failed: {playwright_err}")
                                raise AutoToolError(f"Failed to download video from URL: {playwright_err}")
                        elif is_bilibili:
                            logger.info("yt-dlp download failed. Falling back to Bilibili Playwright downloader...")
                            from app.services.downloader import download_bilibili_with_playwright
                            try:
                                from app.utils.logger import wrap_with_job_context
                                info = await asyncio.get_event_loop().run_in_executor(
                                    None, wrap_with_job_context(job_id, download_bilibili_with_playwright), job.input_path, dest_video
                                )
                                logger.info("Bilibili Playwright downloader succeeded.")
                            except Exception as playwright_err:
                                logger.error(f"Bilibili Playwright downloader failed: {playwright_err}")
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
                    if job.input_aspect_type == "horizontal":
                        snapshot["selected_outputs"] = ["yt_video"]
                    else:
                        snapshot["selected_outputs"] = ["fb_reels", "yt_shorts"]
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
                elif getattr(job, "ocr_only_mode", False):
                    # Run OCR-only transcription for silent/text-based videos
                    try:
                        logger.info("ocr_only_mode is enabled. Running OCR video text extraction...")
                        metadata_path = work_dir / "metadata.json"
                        duration = 30.0
                        if metadata_path.exists():
                            try:
                                with open(metadata_path, "r", encoding="utf-8") as f:
                                    meta = json.load(f)
                                    duration = float(meta.get("duration", 30.0))
                            except Exception:
                                pass
                        dest_video = self._get_dest_video(work_dir)
                        segments = self._extract_text_segments_via_ocr(dest_video, work_dir, duration)
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
                    except Exception as ocr_err:
                        raise AutoToolError(f"OCR transcription failed: {ocr_err}")
                else:
                    # No sidecar SRT, try auto-transcription with faster-whisper if installed
                    try:
                        logger.info("No sidecar SRT found. Initiating Whisper auto-transcription...")
                        audio_path = work_dir / "audio.wav"
                        # Use cached Whisper model; allow concurrent jobs to transcribe in parallel.
                        model = _get_whisper_model()
                        try:
                            segments_iter, info = model.transcribe(
                                str(audio_path),
                                beam_size=5,
                                vad_filter=True,
                                vad_parameters=dict(
                                    threshold=0.35,              # Lower threshold to detect quieter speech (default 0.5)
                                    min_speech_duration_ms=250,  # Detect shorter speech segments (default 250)
                                    min_silence_duration_ms=500, # Treat gaps under 500ms as same sentence (default 2000)
                                    speech_pad_ms=400            # Pad start/end to prevent chopping (default 400)
                                ),
                                condition_on_previous_text=False
                            )
                            segments_list = list(segments_iter)
                        except Exception as transcribe_err:
                            err_str = str(transcribe_err).lower()
                            if "cublas" in err_str or "cuda" in err_str or "cudnn" in err_str or "dll" in err_str:
                                logger.warning(f"Whisper GPU execution failed: {transcribe_err}. Retrying with CPU fallback...")
                                model = _get_whisper_model(force_cpu=True)
                                segments_iter, info = model.transcribe(
                                    str(audio_path),
                                    beam_size=5,
                                    vad_filter=True,
                                    vad_parameters=dict(
                                        threshold=0.35,
                                        min_speech_duration_ms=250,
                                        min_silence_duration_ms=500,
                                        speech_pad_ms=400
                                    ),
                                    condition_on_previous_text=False
                                )
                                segments_list = list(segments_iter)
                            else:
                                raise transcribe_err

                        segments = []
                        for idx, s in enumerate(segments_list):
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
                    snapshot = job.config_snapshot or {}
                    target_lang = snapshot.get("target_language", "vi-VN")
                    target_loc = snapshot.get("target_locale")
                    trans_mode = snapshot.get("translation_mode", "natural")
                    segments = self.translator.translate(
                        segments,
                        tone,
                        target_language=target_lang,
                        target_locale=target_loc,
                        translation_mode=trans_mode
                    )
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
                    snapshot = job.config_snapshot or {}
                    target_lang = snapshot.get("target_language", "vi-VN")
                    target_loc = snapshot.get("target_locale")
                    resolved_voice = self._resolve_tts_voice(target_lang, target_loc, voice)
                    logger.info(f"Resolved TTS voice for language '{target_lang}': {resolved_voice} (original: {voice})")
                    
                    segments = await self.tts_service.generate_voiceovers(
                        segments=segments,
                        work_dir=work_dir,
                        voice=resolved_voice,
                        rate=rate,
                        pitch=pitch
                    )
                    
                    # Prevent voiceover segments and subtitles from overlapping
                    logger.info("Adjusting segment timelines to prevent voiceover/subtitle overlaps...")
                    for i in range(len(segments)):
                        s = segments[i]
                        audio_dur = s.end_ms - s.start_ms
                        if s.tts_path and os.path.exists(s.tts_path):
                            try:
                                audio_dur = self.tts_service.get_audio_duration_ms(Path(s.tts_path))
                            except Exception as e:
                                logger.warning(f"Failed to get audio duration for segment {s.id}: {e}")
                        
                        s.end_ms = s.start_ms + audio_dur
                        
                        if i < len(segments) - 1:
                            s_next = segments[i+1]
                            min_gap = 150  # 150ms natural pause between sentences
                            if s_next.start_ms < s.end_ms + min_gap:
                                old_start = s_next.start_ms
                                s_next.start_ms = s.end_ms + min_gap
                                # Shift its end_ms proportionally so its duration is preserved
                                orig_dur = s_next.end_ms - old_start
                                s_next.end_ms = s_next.start_ms + orig_dur
                                logger.info(f"Shifted Segment {s_next.id} start_ms from {old_start} to {s_next.start_ms} to prevent overlap.")
                                
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
                    original_bgm_name = bgm_name
                    # Map abstract BGM names to actual files in examples/music
                    bgm_mapping = {
                        "dramatic_loop": "leberch-soft-piano-501446",
                        "funny_loop": "lightbeatsmusic-joyful-rhythm-walk-funk-513936",
                        "sad_loop": "leberch-soft-piano-501446"
                    }
                    mapped_name = bgm_mapping.get(bgm_name, bgm_name)
                    music_dir = Path(settings.default_music_folder)
                    
                    # Try mapped name first
                    for ext in [".mp3", ".wav", ".m4a"]:
                        test_path = music_dir / f"{mapped_name}{ext}"
                        if test_path.exists():
                            bgm_path = test_path
                            break
                            
                    # Fallback to original name if mapped name doesn't exist
                    if not bgm_path and mapped_name != original_bgm_name:
                        for ext in [".mp3", ".wav", ".m4a"]:
                            test_path = music_dir / f"{original_bgm_name}{ext}"
                            if test_path.exists():
                                bgm_path = test_path
                                break
                                
                    if not bgm_path:
                        test_path = Path(original_bgm_name)
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
                    # Sync subtitle end time with actual TTS audio duration if TTS is enabled
                    end_ms = s.end_ms
                    if tts_enabled and s.tts_path and os.path.exists(s.tts_path):
                        try:
                            audio_dur = self.tts_service.get_audio_duration_ms(Path(s.tts_path))
                            end_ms = s.start_ms + audio_dur
                        except Exception as e:
                            logger.warning(f"Failed to get audio duration for segment {s.id}: {e}")
                            
                    sub = pysrt.SubRipItem(
                        index=s.id,
                        start=pysrt.SubRipTime(milliseconds=s.start_ms),
                        end=pysrt.SubRipTime(milliseconds=end_ms),
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
                        
                    reframe_mode = "blur_background"
                    crop_layout = None
                    
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
                            subtitle_layout=snapshot.get(f"{out}_subtitle_layout") or snapshot.get("subtitle_layout"),
                            subtitle_style=snapshot.get("subtitle_style", "default"),
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
                            logo_position=snapshot.get("logo_position", "top_left"),
                            logo_layout=snapshot.get("logo_layout"),
                            asset_path=asset_path,
                            asset_layout=snapshot.get("asset_layout"),
                            blur_masks=snapshot.get("blur_masks", []),
                            reverse_video=snapshot.get("reverse_video", False)
                        )
                        
                        # 1. Resolve output export folder (e.g. outputs/page_name/job_id/ or outputs/Completed/job_id/)
                        completed_dir = self._resolve_export_dir(job)
                        completed_dir.mkdir(parents=True, exist_ok=True)
                        
                        # 2. Copy the final video to the export folder
                        dest_completed = completed_dir / filename
                        shutil.copy2(final_video, dest_completed)
                        
                        # 3. Reference the exported video path in job outputs
                        job.outputs[out]["file_path"] = str(dest_completed.resolve())
                        job.outputs[out]["render_status"] = "completed"
                        
                        # Set default job.output_path to the first rendered output
                        if not job.output_path:
                            job.output_path = str(dest_completed.resolve())
                            
                        # 4. Copy srt files if they exist in work dir
                        input_srt = work_dir / "input.srt"
                        if input_srt.exists():
                            shutil.copy2(input_srt, completed_dir / "input.srt")
                        if output_srt.exists():
                            shutil.copy2(output_srt, completed_dir / "output.srt")
                            
                        # 5. Delete duplicate final video from projects dir to save space
                        try:
                            final_video.unlink(missing_ok=True)
                        except Exception as e:
                            logger.warning(f"Failed to delete temp video in projects: {e}")
                            
                        logger.info(f"Successfully rendered format: {out}, exported to {dest_completed}")
                        
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
                
                # Pre-populate snapshot with default values
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

                        snapshot = job.config_snapshot or {}
                        target_lang = snapshot.get("target_language", "vi-VN")
                        target_loc = snapshot.get("target_locale") or "mặc định"
                        summary_prompt = (
                            "facebook_caption phai ngan gon tu 10 den 250 ky tu, chi la caption dang bai, khong viet thanh mo ta dai. "
                            "Bạn là chuyên gia sáng tạo nội dung mạng xã hội đa kênh. Hãy dựa vào nội dung đối thoại bên dưới "
                            f"để viết các captions, tiêu đề giật gân chuẩn SEO và các hashtags bằng ngôn ngữ đích '{target_lang}' (locale: '{target_loc}') "
                            "phù hợp cho từng nền tảng: Facebook Reels, YouTube Shorts, và YouTube Video thường. "
                            f"Lưu ý đặc biệt: Tất cả các trường văn bản mô tả, tiêu đề và hashtag trong JSON kết quả PHẢI được viết bằng chính ngôn ngữ đích '{target_lang}'. "
                            "Trả về định dạng JSON đúng schema được cung cấp.\n\n"
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
                        facebook_caption = " ".join(facebook_caption.split()).strip()
                        facebook_hashtags = ai_data.get("facebook_hashtags", facebook_hashtags)
                        facebook_hashtags = " ".join(facebook_hashtags.split()).strip()
                        
                        # Smart truncate combined Facebook Reels caption (caption + hashtags) to strictly under 400 chars
                        max_total_len = 395
                        combined_len = len(facebook_caption) + 1 + len(facebook_hashtags)
                        if combined_len > max_total_len:
                            # Keep hashtags intact, truncate the caption text (account for 3 characters of "...")
                            allowed_caption_len = max_total_len - len(facebook_hashtags) - 1 - 3
                            if allowed_caption_len > 10:
                                facebook_caption = facebook_caption[:allowed_caption_len].strip() + "..."
                            else:
                                # Fallback if hashtags are too long
                                combined = f"{facebook_caption} {facebook_hashtags}"
                                facebook_caption = combined[:max_total_len].strip()
                                facebook_hashtags = ""
                                
                        youtube_shorts_title = ai_data.get("youtube_shorts_title", youtube_shorts_title)
                        youtube_shorts_description = ai_data.get("youtube_shorts_description", youtube_shorts_description)
                        youtube_shorts_tags = ai_data.get("youtube_shorts_tags", youtube_shorts_tags)
                        youtube_video_title = ai_data.get("youtube_video_title", youtube_video_title)
                        youtube_video_description = ai_data.get("youtube_video_description", youtube_video_description)
                        youtube_video_tags = ai_data.get("youtube_video_tags", youtube_video_tags)
                        
                        # Save to job config snapshot so client can display it
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
                        
                # Save the short posting caption only.
                caption_file = output_dir / "caption.txt"
                with open(caption_file, "w", encoding="utf-8") as f:
                    combined_out = f"{facebook_caption} {facebook_hashtags}".strip()
                    # Final safety check on total length
                    if len(combined_out) > 398:
                        combined_out = combined_out[:398].strip()
                    f.write(f"{combined_out}\n")
                    
                completed_dir = self._resolve_export_dir(job)
                completed_dir.mkdir(parents=True, exist_ok=True)
                dest_completed_caption = completed_dir / "caption.txt"
                try:
                    shutil.copy2(caption_file, dest_completed_caption)
                    # Delete duplicate caption file in projects
                    caption_file.unlink(missing_ok=True)
                except Exception as copy_err:
                    logger.warning(f"Failed to copy caption to Completed folder: {copy_err}")
                    
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
            from app.utils.logger import set_current_job_id
            set_current_job_id(None)
            if 'file_handler' in locals():
                try:
                    logging.getLogger().removeHandler(file_handler)
                    file_handler.close()
                except Exception:
                    pass
            try:
                success = (job.status == "completed")
                self.cleanup_job_files(job_id, success)
            except Exception as clean_err:
                logger.warning(f"Error during intermediate files cleanup: {clean_err}")

    def cleanup_job_files(self, job_id: str, success: bool):
        """
        Clean up temporary and intermediate files from a job directory.
        """
        from app.config import settings
        from pathlib import Path
        import shutil
        
        if not settings.cleanup_intermediate_files:
            return
            
        job_dir = self.projects_dir / job_id
        if not job_dir.exists():
            return
            
        work_dir = job_dir / "work"
        output_dir = job_dir / "output"
        
        if success:
            # Delete specific non-rendering intermediate files in work
            intermediate_names = [
                "output.ass"
            ]
            for name in intermediate_names:
                p = work_dir / name
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
                        
            # Delete output folder in projects since final videos are saved only in outputs folder
            if output_dir.exists():
                try:
                    shutil.rmtree(output_dir, ignore_errors=True)
                except Exception:
                    pass
                        
            # Delete tts/ folder in work_dir
            tts_dir = work_dir / "tts"
            if tts_dir.exists():
                try:
                    shutil.rmtree(tts_dir, ignore_errors=True)
                except Exception:
                    pass
                    
            # Delete run.log and job_config.json if keep_debug_on_success is False
            if not settings.keep_debug_on_success:
                for name in ["run.log", "job_config.json"]:
                    p = job_dir / name
                    if p.exists():
                        try:
                            p.unlink()
                        except Exception:
                            pass
                            
        else:
            # If job failed and we do NOT want to keep temp/debug files on failure
            if not settings.keep_temp_on_failure:
                try:
                    for p in list(work_dir.glob("*")):
                        if p.suffix.lower() != ".srt" and p.is_file():
                            p.unlink()
                    shutil.rmtree(work_dir / "tts", ignore_errors=True)
                except Exception:
                    pass
