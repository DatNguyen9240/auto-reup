import os
import json
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

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
    voice: str = "vi-VN-HoaiMyNeural"
    rate: str = "+0%"
    pitch: str = "+0Hz"
    bgm: Optional[str] = None
    logo: Optional[str] = None
    mask: bool = True

class SegmentUpdateRequest(BaseModel):
    segments: List[Segment]
    reset_from_tts: bool = False
    tone: str = "review_phim"
    voice: str = "vi-VN-HoaiMyNeural"
    rate: str = "+0%"
    pitch: str = "+0Hz"
    bgm: Optional[str] = None
    logo: Optional[str] = None
    mask: bool = True

async def run_pipeline_bg(
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
        await runner.run(
            job_id=job_id,
            tone=tone,
            voice=voice,
            rate=rate,
            pitch=pitch,
            bgm_name=bgm_name,
            logo_path=logo_path,
            mask_subtitle=mask_subtitle
        )
    except Exception as e:
        logger.error(f"Error running pipeline in background for {job_id}: {e}")
    finally:
        running_jobs.discard(job_id)

@app.post("/api/jobs")
async def create_job(req: JobCreateRequest, background_tasks: BackgroundTasks):
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

    background_tasks.add_task(
        run_pipeline_bg,
        job_id=job_id,
        tone=req.tone,
        voice=req.voice,
        rate=req.rate,
        pitch=req.pitch,
        bgm_name=req.bgm,
        logo_path=logo_path,
        mask_subtitle=req.mask
    )

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
async def update_transcript(job_id: str, req: SegmentUpdateRequest, background_tasks: BackgroundTasks):
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

        background_tasks.add_task(
            run_pipeline_bg,
            job_id=job_id,
            tone=req.tone,
            voice=req.voice,
            rate=req.rate,
            pitch=req.pitch,
            bgm_name=req.bgm,
            logo_path=logo_path,
            mask_subtitle=req.mask
        )
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

@app.get("/")
def read_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Frontend Static SPA index.html is missing. Please create it.</h1>")
    return FileResponse(index_path)
