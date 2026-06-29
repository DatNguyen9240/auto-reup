import os
import json
import logging
import asyncio
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from app.config import settings, AVAILABLE_VOICES, AVAILABLE_TONES, AVAILABLE_RATES, AVAILABLE_PITCHES
from app.core.pipeline import PipelineRunner
from app.storage.json_store import JsonStore
from app.models.job import Job
from app.models.segment import Segment
from app.utils.logger import get_logger

logger = get_logger("Server")

app = FastAPI(title="AutoTool Web API", description="Backend services for Auto Video Translation and Reup")

# Define paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_DIR = PROJECT_ROOT / "projects"
STATIC_DIR = PROJECT_ROOT / "app" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

runner = PipelineRunner(PROJECTS_DIR)
store = JsonStore(PROJECTS_DIR)

# In-memory progress tracker to lock and override state if running
running_jobs = set()

class JobCreateRequest(BaseModel):
    input_video: str
    tone: str = "review_phim"
    voice: str = settings.default_voice
    rate: str = settings.default_rate
    pitch: str = settings.default_pitch
    bgm: Optional[str] = None
    logo: Optional[str] = None
    mask: bool = True

class SegmentUpdateRequest(BaseModel):
    segments: List[Segment]
    reset_from_tts: bool = False
    tone: str = "review_phim"
    voice: str = settings.default_voice
    rate: str = settings.default_rate
    pitch: str = settings.default_pitch
    bgm: Optional[str] = None
    logo: Optional[str] = None
    mask: bool = True

class ChannelCreateRequest(BaseModel):
    name: str
    tone: str = "review_phim"
    voice: str = settings.default_voice
    rate: str = settings.default_rate
    pitch: str = settings.default_pitch
    bgm: Optional[str] = None
    logo: Optional[str] = None
    mask: bool = True

class ChannelProcessRequest(BaseModel):
    input_video: str

CHANNELS_FILE = PROJECTS_DIR / "channels.json"

def _load_channels() -> List[Dict[str, Any]]:
    if not CHANNELS_FILE.exists():
        default_channels = [
            {
                "id": "chan_review_phim",
                "name": "Kênh Review Phim",
                "tone": "review_phim",
                "voice": settings.default_voice,
                "rate": settings.default_rate,
                "pitch": settings.default_pitch,
                "bgm": None,
                "logo": None,
                "mask": True
            },
            {
                "id": "chan_hai_huoc",
                "name": "Kênh Hài Hước",
                "tone": "funny",
                "voice": "vi-VN-NamMinhNeural",
                "rate": "+10%",
                "pitch": "+0Hz",
                "bgm": "funny_loop",
                "logo": None,
                "mask": True
            }
        ]
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
                json.dump(default_channels, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error seeding channels: {e}")
        return default_channels
        
    try:
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading channels: {e}")
        return []

def _save_channels(channels: List[Dict[str, Any]]):
    try:
        with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(channels, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving channels: {e}")

pipeline_lock = threading.Lock()

def run_pipeline_in_thread(
    job_id: str,
    tone: str,
    voice: str,
    rate: str,
    pitch: str,
    bgm_name: Optional[str],
    logo_path: Optional[Path],
    mask_subtitle: bool
):
    running_jobs.add(job_id)
    try:
        with pipeline_lock:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(runner.run(
                    job_id=job_id,
                    tone=tone,
                    voice=voice,
                    rate=rate,
                    pitch=pitch,
                    bgm_name=bgm_name,
                    logo_path=logo_path,
                    mask_subtitle=mask_subtitle
                ))
            finally:
                loop.close()
    except Exception as e:
        logger.error(f"Error running pipeline in thread for {job_id}: {e}")
    finally:
        running_jobs.discard(job_id)

@app.post("/api/jobs")
async def create_job(req: JobCreateRequest):
    input_video = req.input_video
    is_url = input_video.startswith("http://") or input_video.startswith("https://")
    
    if not is_url:
        input_path = Path(input_video)
        if not input_path.is_absolute():
            input_path = PROJECT_ROOT / input_path
        if not input_path.exists():
            raise HTTPException(status_code=400, detail=f"Input video file not found at: {input_video}")
        job_id = f"job_{input_path.stem}"
    else:
        import hashlib
        url_hash = hashlib.md5(input_video.encode('utf-8')).hexdigest()[:8]
        job_id = f"job_url_{url_hash}"

    job = store.load_job(job_id)
    if job and (job.status == "running" or job_id in running_jobs):
        return {"job_id": job_id, "status": "running", "message": "Job is already running"}

    logo_path = None
    if req.logo:
        logo_path = Path(req.logo)
        if not logo_path.is_absolute():
            logo_path = PROJECT_ROOT / logo_path

    if not job:
        job = runner.create_job(str(input_path) if not is_url else input_video, job_id)
    else:
        job.status = "created"
        for step in job.steps:
            job.steps[step] = "pending"
        job.errors = []
        store.save_job(job)

    thread = threading.Thread(
        target=run_pipeline_in_thread,
        args=(job_id, req.tone, req.voice, req.rate, req.pitch, req.bgm, logo_path, req.mask)
    )
    thread.start()

    return {"job_id": job_id, "status": "running", "message": "Job started successfully"}

@app.get("/api/jobs")
def list_jobs():
    jobs = []
    if PROJECTS_DIR.exists():
        for item in PROJECTS_DIR.iterdir():
            if item.is_dir():
                state_file = item / "job_state.json"
                if state_file.exists():
                    try:
                        with open(state_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if data.get("job_id") in running_jobs:
                                data["status"] = "running"
                            jobs.append(data)
                    except Exception as e:
                        logger.error(f"Error loading state from {state_file}: {e}")
    jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jobs

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.job_id in running_jobs:
        job.status = "running"
    return job

@app.get("/api/jobs/{job_id}/transcript")
def get_transcript(job_id: str):
    segments = store.load_translated(job_id)
    if not segments:
        segments = store.load_transcript(job_id)
    if not segments:
        raise HTTPException(status_code=404, detail="No transcript segments found for this job.")
    return segments

@app.put("/api/jobs/{job_id}/transcript")
async def update_transcript(job_id: str, req: SegmentUpdateRequest):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
    if job.job_id in running_jobs:
        raise HTTPException(status_code=400, detail="Cannot edit transcript while job is running")

    store.save_translated(job_id, req.segments)
    
    if req.reset_from_tts:
        job.steps["tts"] = "pending"
        job.steps["mix_audio"] = "pending"
        job.steps["render"] = "pending"
        job.steps["metadata"] = "pending"
        job.status = "created"
        job.errors = []
        store.save_job(job)
        
        logo_path = None
        if req.logo:
            logo_path = Path(req.logo)
            if not logo_path.is_absolute():
                logo_path = PROJECT_ROOT / logo_path

        thread = threading.Thread(
            target=run_pipeline_in_thread,
            args=(job_id, req.tone, req.voice, req.rate, req.pitch, req.bgm, logo_path, req.mask)
        )
        thread.start()
        return {"status": "re-running", "message": "Transcript saved and pipeline restarted from TTS step"}
        
    return {"status": "saved", "message": "Transcript saved successfully"}

@app.get("/api/jobs/{job_id}/video")
def get_video(job_id: str):
    job = store.load_job(job_id)
    if not job or not job.output_path:
        raise HTTPException(status_code=404, detail="Job output path not found")
        
    video_path = Path(job.output_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Video file not found at: {video_path}")
        
    return FileResponse(video_path, media_type="video/mp4")

@app.get("/api/jobs/{job_id}/caption")
def get_caption(job_id: str):
    job = store.load_job(job_id)
    if not job or not job.output_path:
        raise HTTPException(status_code=404, detail="Job not found")
        
    caption_path = Path(job.output_path).parent / "caption.txt"
    if not caption_path.exists():
        return {"content": "Caption file has not been generated yet."}
        
    try:
        with open(caption_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read caption: {e}")

@app.post("/api/cookies/generate")
def generate_cookies_endpoint(background_tasks: BackgroundTasks):
    from app.services.downloader import auto_generate_douyin_cookies
    cookie_path = PROJECT_ROOT / "cookies.txt"
    
    def run_generate():
        try:
            logger.info("Starting background cookies generation...")
            auto_generate_douyin_cookies(cookie_path)
        except Exception as e:
            logger.error(f"Failed to run auto-generate cookies: {e}")
        
    background_tasks.add_task(run_generate)
    return {"status": "running", "message": "Playwright cookie generation started in background"}

@app.post("/api/cookies/export")
def export_cookies_endpoint(background_tasks: BackgroundTasks):
    from app.services.downloader import export_cookies_from_browser
    cookie_path = PROJECT_ROOT / "cookies.txt"
    
    def run_export():
        try:
            logger.info("Starting background cookies export from browser...")
            export_cookies_from_browser(cookie_path)
        except Exception as e:
            logger.error(f"Failed to run export cookies: {e}")
        
    background_tasks.add_task(run_export)
    return {"status": "running", "message": "Browser cookie export started in background"}

@app.get("/api/media/scan")
def scan_media(path: Optional[str] = None):
    scan_path = path or settings.default_source_folder or str(PROJECT_ROOT)
    p = Path(scan_path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Source folder not found or is not a directory: {scan_path}")

    # Video extensions to scan
    video_extensions = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
    videos = []

    try:
        # Recursively search for video files
        for file in p.rglob("*"):
            if file.is_file() and file.suffix.lower() in video_extensions:
                # Exclude files inside projects/ or venv/ or .git/ or docs/
                parts = file.relative_to(p).parts
                if any(x in parts for x in ["projects", "venv", ".git", "docs", "app/static", "app"]):
                    continue
                
                rel_path = file.relative_to(p)
                videos.append({
                    "name": file.name,
                    "relative_path": str(rel_path).replace("\\", "/"),
                    "absolute_path": str(file.resolve()),
                    "folder": str(rel_path.parent).replace("\\", "/") if len(parts) > 1 else "",
                    "size_mb": round(file.stat().st_size / (1024 * 1024), 2)
                })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scan directory: {e}")

    return {
        "scan_path": str(p.resolve()),
        "videos": videos
    }

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
    if job_id in running_jobs:
        raise HTTPException(status_code=400, detail="Cannot delete a running job")
        
    job_dir = store.get_job_dir(job_id)
    if job_dir.exists():
        import shutil
        try:
            shutil.rmtree(job_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete job directory: {e}")
            
    return {"status": "deleted", "message": f"Job {job_id} has been deleted successfully"}

@app.get("/api/jobs/{job_id}/logs")
def get_job_logs(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
    log_file = store.get_job_dir(job_id) / "run.log"
    if not log_file.exists():
        return {"logs": "Chưa có nhật ký hoạt động."}
        
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        return {"logs": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {e}")

@app.get("/api/config")
def get_global_config():
    return {
        "voices": AVAILABLE_VOICES,
        "tones": AVAILABLE_TONES,
        "rates": AVAILABLE_RATES,
        "pitches": AVAILABLE_PITCHES
    }

@app.get("/api/voices")
def get_voices():
    return AVAILABLE_VOICES

@app.get("/api/channels")
def list_channels():
    return _load_channels()

@app.post("/api/channels")
def create_channel(req: ChannelCreateRequest):
    import uuid
    channels = _load_channels()
    chan_id = f"chan_{uuid.uuid4().hex[:8]}"
    new_chan = {
        "id": chan_id,
        "name": req.name,
        "tone": req.tone,
        "voice": req.voice,
        "rate": req.rate,
        "pitch": req.pitch,
        "bgm": req.bgm,
        "logo": req.logo,
        "mask": req.mask
    }
    channels.append(new_chan)
    _save_channels(channels)
    return new_chan

@app.put("/api/channels/{channel_id}")
def update_channel(channel_id: str, req: ChannelCreateRequest):
    channels = _load_channels()
    found = False
    for chan in channels:
        if chan["id"] == channel_id:
            chan["name"] = req.name
            chan["tone"] = req.tone
            chan["voice"] = req.voice
            chan["rate"] = req.rate
            chan["pitch"] = req.pitch
            chan["bgm"] = req.bgm
            chan["logo"] = req.logo
            chan["mask"] = req.mask
            found = True
            break
            
    if not found:
        raise HTTPException(status_code=404, detail="Channel not found")
        
    _save_channels(channels)
    return {"status": "success"}

@app.delete("/api/channels/{channel_id}")
def delete_channel(channel_id: str):
    channels = _load_channels()
    new_channels = [c for c in channels if c["id"] != channel_id]
    if len(new_channels) == len(channels):
        raise HTTPException(status_code=404, detail="Channel not found")
    _save_channels(new_channels)
    return {"status": "deleted"}

@app.post("/api/channels/{channel_id}/process")
def process_channel_video(channel_id: str, req: ChannelProcessRequest):
    channels = _load_channels()
    channel = next((c for c in channels if c["id"] == channel_id), None)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
        
    import re
    input_video = req.input_video.strip()
    is_url = input_video.startswith("http://") or input_video.startswith("https://")
    
    if not is_url:
        input_path = Path(input_video)
        if not input_path.is_absolute():
            input_path = PROJECT_ROOT / input_path
        if not input_path.exists():
            raise HTTPException(status_code=400, detail=f"Input video file not found at: {input_video}")
        # Generate safe job_id
        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', input_path.stem)[:12]
        import hashlib
        path_hash = hashlib.md5(str(input_path).encode('utf-8')).hexdigest()[:4]
        job_id = f"job_{safe_name}_{path_hash}"
    else:
        import hashlib
        url_hash = hashlib.md5(input_video.encode('utf-8')).hexdigest()[:8]
        job_id = f"job_url_{url_hash}"
        
    if job_id in running_jobs:
        raise HTTPException(status_code=400, detail="This video is already being processed.")
        
    # Get logo path
    logo_path = None
    logo_str = channel.get("logo")
    if logo_str:
        logo_path = Path(logo_str)
        if not logo_path.is_absolute():
            logo_path = PROJECT_ROOT / logo_path
            
    # Load or create job
    job = store.load_job(job_id)
    if not job:
        job = runner.create_job(str(input_path) if not is_url else input_video, job_id)
    else:
        job.status = "created"
        for step in job.steps:
            job.steps[step] = "pending"
        job.errors = []
        store.save_job(job)
        
    # Inject channel settings
    job.tone = channel["tone"]
    job.voice = channel["voice"]
    job.rate = channel["rate"]
    job.pitch = channel["pitch"]
    job.bgm = channel["bgm"]
    job.logo = channel.get("logo")
    job.mask = channel["mask"]
    store.save_job(job)
    
    # Start thread
    thread = threading.Thread(
        target=run_pipeline_in_thread,
        args=(job_id, job.tone, job.voice, job.rate, job.pitch, job.bgm, logo_path, job.mask)
    )
    thread.start()
    
    return {"status": "started", "job_id": job_id}

@app.get("/")


def read_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Frontend Static SPA index.html is missing. Please create it.</h1>")
    return FileResponse(index_path)

