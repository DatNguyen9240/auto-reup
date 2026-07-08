import sys
import re
from pathlib import Path

# Add project root to sys.path to allow direct execution
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import os
import json
import logging
import asyncio
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from app.config import settings, AVAILABLE_VOICES, AVAILABLE_TONES, AVAILABLE_RATES, AVAILABLE_PITCHES, EMOTION_PRESETS
from app.core.pipeline import PipelineRunner
from app.storage.json_store import JsonStore
from app.models.job import Job
from app.models.segment import Segment
from app.utils.logger import get_logger, set_current_job_id
from app.utils.file_utils import read_json

logger = get_logger("Server")

# Define paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_DIR = PROJECT_ROOT / "projects"
STATIC_DIR = PROJECT_ROOT / "app" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

from fastapi.staticfiles import StaticFiles

app = FastAPI(title="AutoTool Web API", description="Backend services for Auto Video Translation and Reup")

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Mount static subdirectories
app.mount("/css", StaticFiles(directory=STATIC_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=STATIC_DIR / "js"), name="js")
app.mount("/views", StaticFiles(directory=STATIC_DIR / "views"), name="views")

runner = PipelineRunner(PROJECTS_DIR)
store = JsonStore(PROJECTS_DIR)

# In-memory progress tracker to lock and override state if running
running_jobs = set()

def job_progress(job: Job) -> int:
    steps = job.steps or {}
    if not steps:
        return 0
    return round((sum(1 for s in steps.values() if s == "completed") / len(steps)) * 100)

def enrich_job_data(data: Dict[str, Any]) -> Dict[str, Any]:
    job = Job(**data)
    data.update({
        "progress": job_progress(job),
        "thumbnail_url": f"/api/jobs/{job.job_id}/video" if job.status == "completed" and job.output_path else None,
        "is_published": getattr(job, "is_published", False),
    })
    return data

class JobCreateRequest(BaseModel):
    input_video: str
    tone: str = "review_phim"
    voice: str = settings.default_voice
    rate: str = settings.default_rate
    pitch: str = settings.default_pitch
    bgm: Optional[str] = None
    logo: Optional[str] = None
    mask: bool = True
    tts_enabled: bool = True
    subtitles_enabled: bool = True
    subtitle_cover_mode: str = settings.subtitle_cover_mode
    subtitle_bg_opacity: float = settings.subtitle_bg_opacity
    subtitle_mask_padding_x: int = settings.subtitle_mask_padding_x
    subtitle_mask_padding_y: int = settings.subtitle_mask_padding_y
    ocr_sample_interval_sec: float = settings.ocr_sample_interval_sec
    ocr_crop_bottom_ratio: float = settings.ocr_crop_bottom_ratio
    channel_folder: Optional[str] = None
    platform_folder: Optional[str] = None
    channel_id: Optional[str] = None
    selected_outputs: Optional[List[str]] = None
    config_snapshot: Optional[Dict[str, Any]] = None
    ocr_only_mode: bool = False
    target_language: str = "vi-VN"
    target_locale: Optional[str] = None
    translation_mode: str = "natural"
    subtitle_style: str = "default"
    reverse_video: bool = False

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
    tts_enabled: bool = True
    subtitles_enabled: bool = True
    subtitle_cover_mode: str = settings.subtitle_cover_mode
    subtitle_bg_opacity: float = settings.subtitle_bg_opacity
    subtitle_mask_padding_x: int = settings.subtitle_mask_padding_x
    subtitle_mask_padding_y: int = settings.subtitle_mask_padding_y
    ocr_sample_interval_sec: float = settings.ocr_sample_interval_sec
    ocr_crop_bottom_ratio: float = settings.ocr_crop_bottom_ratio
    channel_folder: Optional[str] = None
    platform_folder: Optional[str] = None
    ocr_only_mode: bool = False
    reverse_video: bool = False

class SubtitleLayoutRequest(BaseModel):
    subtitle_x_percent: float = 0.08
    subtitle_y_percent: float = 0.56
    subtitle_width_percent: float = 0.84
    subtitle_height_percent: float = 0.08
    subtitle_bg_opacity: float = 0.42
    background_opacity: Optional[float] = None
    preset: str = "custom"
    asset: Optional[str] = None
    asset_x_percent: Optional[float] = None
    asset_y_percent: Optional[float] = None
    asset_width_percent: Optional[float] = None
    asset_height_percent: Optional[float] = None
    asset_opacity: Optional[float] = 1.0
    asset_color: Optional[str] = None
    logo_x_percent: Optional[float] = None
    logo_y_percent: Optional[float] = None
    logo_width_percent: Optional[float] = None
    logo_height_percent: Optional[float] = None
    blur_masks: Optional[List[Dict[str, Any]]] = None
    fb_reels_subtitle_layout: Optional[Dict[str, Any]] = None
    yt_shorts_subtitle_layout: Optional[Dict[str, Any]] = None
    yt_video_subtitle_layout: Optional[Dict[str, Any]] = None
    subtitle_style: str = "default"

def _normalize_subtitle_layout(req: SubtitleLayoutRequest) -> Dict[str, Any]:
    layout = {
        "x": max(0.0, min(0.95, req.subtitle_x_percent)),
        "y": max(0.0, min(0.95, req.subtitle_y_percent)),
        "width": max(0.10, min(1.0, req.subtitle_width_percent)),
        "height": max(0.04, min(0.40, req.subtitle_height_percent)),
    }
    layout["width"] = min(layout["width"], 1.0 - layout["x"])
    layout["height"] = min(layout["height"], 1.0 - layout["y"])
    opacity = req.background_opacity if req.background_opacity is not None else req.subtitle_bg_opacity
    return {
        "layout": layout,
        "opacity": max(0.0, min(1.0, opacity)),
        "preset": req.preset or "custom",
    }

def _save_subtitle_layout_snapshot(job: Job, req: SubtitleLayoutRequest) -> Dict[str, Any]:
    normalized = _normalize_subtitle_layout(req)
    snapshot = dict(job.config_snapshot or {})
    snapshot["subtitle_layout"] = normalized["layout"]
    snapshot["subtitle_bg_opacity"] = normalized["opacity"]
    snapshot["subtitle_preset"] = normalized["preset"]
    snapshot["subtitle_cover_mode"] = "text_box_only"
    snapshot["subtitle_style"] = req.subtitle_style
    
    if req.asset is not None:
        snapshot["asset"] = req.asset
    if req.asset_x_percent is not None and req.asset_y_percent is not None:
        asset_type = "image"
        if req.asset == "__color_mask__":
            asset_type = "color"
        elif req.asset == "__blur_mask__":
            asset_type = "blur"
            
        snapshot["asset_layout"] = {
            "type": asset_type,
            "x_percent": req.asset_x_percent,
            "y_percent": req.asset_y_percent,
            "width_percent": req.asset_width_percent or 0.20,
            "height_percent": req.asset_height_percent or 0.08,
            "opacity": req.asset_opacity or 1.0,
            "color": req.asset_color or "#000000"
        }
        
    if req.logo_x_percent is not None and req.logo_y_percent is not None:
        if req.logo_x_percent == -1 and req.logo_y_percent == -1:
            snapshot["logo"] = ""
            snapshot["logo_layout"] = None
        else:
            snapshot["logo_layout"] = {
                "x_percent": req.logo_x_percent,
                "y_percent": req.logo_y_percent,
                "width_percent": req.logo_width_percent,
                "height_percent": req.logo_height_percent
            }

    if req.blur_masks is not None:
        snapshot["blur_masks"] = req.blur_masks
        
    if req.fb_reels_subtitle_layout is not None:
        snapshot["fb_reels_subtitle_layout"] = req.fb_reels_subtitle_layout
    if req.yt_shorts_subtitle_layout is not None:
        snapshot["yt_shorts_subtitle_layout"] = req.yt_shorts_subtitle_layout
    if req.yt_video_subtitle_layout is not None:
        snapshot["yt_video_subtitle_layout"] = req.yt_video_subtitle_layout

    job.config_snapshot = snapshot
    store.save_job(job)
    with open(store.get_job_dir(job.job_id) / "job_config.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    return normalized

def job_work_dir(job: Job) -> Path:
    return store.get_job_dir(job.job_id) / "work"

def job_output_dir(job: Job) -> Path:
    return store.get_job_dir(job.job_id) / "output"
    

pipeline_semaphore = threading.Semaphore(settings.max_concurrent_jobs)

def resolve_logo_path(logo: Optional[str], channel_id: Optional[str] = None) -> Optional[Path]:
    # 1. Priority: If channel_id is provided, check the page directory first for custom logo files
    if channel_id:
        try:
            channels = load_channels_data()
            chan = next((c for c in channels if c.get("id") == channel_id), None)
            if chan:
                chan_dir = resolve_channel_path(chan.get("name"), chan.get("path"))
                name = chan.get("name")
                for candidate in ["logo.png", "logo.jpg", f"logo_{channel_id}.png", f"logo_{channel_id}.jpg", f"{name}.png", f"{name}.jpg"]:
                    # Try assets subfolder first, then root of channel dir
                    p_assets = chan_dir / "assets" / candidate
                    if p_assets.exists() and p_assets.is_file():
                        return p_assets
                    p_root = chan_dir / candidate
                    if p_root.exists() and p_root.is_file():
                        return p_root
        except Exception as e:
            logger.error(f"Error checking page-specific logo file: {e}")

    # 2. Fallback: Resolve custom logo string if provided
    if logo:
        # A. Global overlay
        overlay_path = PROJECT_ROOT / "examples" / "overlay" / logo
        if overlay_path.exists() and overlay_path.is_file():
            return overlay_path
            
        # B. Absolute path
        logo_path = Path(logo)
        if logo_path.is_absolute() and logo_path.exists():
            return logo_path
            
        # C. Relative to project root
        proj_path = PROJECT_ROOT / logo
        if proj_path.exists() and proj_path.is_file():
            return proj_path
            
        # D. Relative to channel folder if channel_id is provided
        if channel_id:
            try:
                channels = load_channels_data()
                chan = next((c for c in channels if c.get("id") == channel_id), None)
                if chan:
                    chan_dir = resolve_channel_path(chan.get("name"), chan.get("path"))
                    chan_logo_path = chan_dir / logo
                    if chan_logo_path.exists() and chan_logo_path.is_file():
                        return chan_logo_path
                        
                    root_logo_path = chan_dir / Path(logo).name
                    if root_logo_path.exists() and root_logo_path.is_file():
                        return root_logo_path
            except Exception as e:
                logger.error(f"Failed resolving channel-specific logo: {e}")
            
    # 3. Fallback: Check if channel has a specific logo name registered
    if channel_id:
        try:
            channels = load_channels_data()
            chan = next((c for c in channels if c.get("id") == channel_id), None)
            if chan:
                if chan.get("logo"):
                    p_logo = chan.get("logo")
                    p_logo_path = PROJECT_ROOT / "examples" / "overlay" / p_logo
                    if p_logo_path.exists() and p_logo_path.is_file():
                        return p_logo_path
                    p_logo_abs = Path(p_logo)
                    if p_logo_abs.is_absolute() and p_logo_abs.exists():
                        return p_logo_abs
        except Exception as e:
            logger.error(f"Error checking channel logo fallback: {e}")
            
    return None

@app.get("/api/jobs/{job_id}/assets")
def get_job_assets(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    assets = []
    
    # 1. Global assets
    global_dir = PROJECT_ROOT / "examples" / "overlay"
    if global_dir.exists():
        for f in global_dir.iterdir():
            if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                assets.append(f.name)
                
    # 2. Channel specific assets (read from channel folder / and channel/assets/)
    snapshot = job.config_snapshot or {}
    channel_id = snapshot.get("channel_id") or job.channel_id
    if channel_id:
        try:
            channels = load_channels_data()
            chan = next((c for c in channels if c.get("id") == channel_id), None)
            if chan:
                chan_dir = resolve_channel_path(chan.get("name"), chan.get("path"))
                if chan_dir.exists():
                    for f in chan_dir.iterdir():
                        if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                            assets.append(f.name)
                            
                assets_sub = chan_dir / "assets"
                if assets_sub.exists() and assets_sub.is_dir():
                    for f in assets_sub.iterdir():
                        if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                            assets.append(f"assets/{f.name}")
        except Exception as e:
            logger.error(f"Error loading channel specific assets: {e}")
            
    return sorted(list(set(assets)))

@app.get("/api/assets/file")
def get_asset_file(name: str, job_id: Optional[str] = None):
    channel_id = None
    if job_id:
        job = store.load_job(job_id)
        if job:
            snapshot = job.config_snapshot or {}
            channel_id = snapshot.get("channel_id") or job.channel_id
            
    asset_path = resolve_logo_path(name, channel_id)
    if not asset_path or not asset_path.exists():
        raise HTTPException(status_code=404, detail="Asset file not found")
        
    media_type = "image/png"
    if asset_path.suffix.lower() in {".jpg", ".jpeg"}:
        media_type = "image/jpeg"
    return FileResponse(asset_path, media_type=media_type)

def pipeline_args_from_snapshot(job: Job) -> tuple:
    snapshot = job.config_snapshot or {}
    return (
        job.job_id,
        snapshot.get("tone", "review_phim"),
        snapshot.get("voice", settings.default_voice),
        snapshot.get("rate", settings.default_rate),
        snapshot.get("pitch", settings.default_pitch),
        snapshot.get("bgm") or None,
        resolve_logo_path(snapshot.get("logo"), snapshot.get("channel_id")),
        bool(snapshot.get("mask", True)),
        bool(snapshot.get("tts_enabled", True)),
        bool(snapshot.get("subtitles_enabled", True)),
        snapshot.get("subtitle_cover_mode", settings.subtitle_cover_mode),
        float(snapshot.get("subtitle_bg_opacity", settings.subtitle_bg_opacity)),
        int(snapshot.get("subtitle_mask_padding_x", settings.subtitle_mask_padding_x)),
        int(snapshot.get("subtitle_mask_padding_y", settings.subtitle_mask_padding_y)),
        float(snapshot.get("ocr_sample_interval_sec", settings.ocr_sample_interval_sec)),
        float(snapshot.get("ocr_crop_bottom_ratio", settings.ocr_crop_bottom_ratio)),
    )

def enqueue_pipeline_job(job: Job, args: Optional[tuple] = None) -> bool:
    if job.job_id in running_jobs:
        logger.info(f"Job {job.job_id} is already enqueued/running.")
        return False
    args = args or pipeline_args_from_snapshot(job)
    job.status = "queued"
    if not job.current_step:
        job.current_step = "intake"
    store.save_job(job)
    logger.info(f"Enqueued job: {job.job_id}")
    thread = threading.Thread(target=run_pipeline_in_thread, args=args, daemon=True)
    running_jobs.add(job.job_id)
    thread.start()
    return True

def requeue_stuck_jobs_on_startup():
    recoverable = {"created", "queued", "processing", "running", "rendering"}
    if not PROJECTS_DIR.exists():
        return
    for item in PROJECTS_DIR.iterdir():
        if not item.is_dir():
            continue
        job = store.load_job(item.name)
        if not job or job.status not in recoverable:
            continue
        if job.job_id in running_jobs:
            continue
        logger.info(f"Recovering stuck job on startup: {job.job_id} status={job.status}")
        enqueue_pipeline_job(job)

@app.on_event("startup")
def startup_requeue_jobs():
    threading.Thread(target=requeue_stuck_jobs_on_startup, daemon=True).start()

def run_pipeline_in_thread(
    job_id: str,
    tone: str,
    voice: str,
    rate: str,
    pitch: str,
    bgm_name: Optional[str],
    logo_path: Optional[Path],
    mask_subtitle: bool,
    tts_enabled: bool = True,
    subtitles_enabled: bool = True,
    subtitle_cover_mode: str = settings.subtitle_cover_mode,
    subtitle_bg_opacity: float = settings.subtitle_bg_opacity,
    subtitle_mask_padding_x: int = settings.subtitle_mask_padding_x,
    subtitle_mask_padding_y: int = settings.subtitle_mask_padding_y,
    ocr_sample_interval_sec: float = settings.ocr_sample_interval_sec,
    ocr_crop_bottom_ratio: float = settings.ocr_crop_bottom_ratio,
):
    try:
        set_current_job_id(job_id)
        with pipeline_semaphore:
            job = store.load_job(job_id)
            if job:
                job.status = "processing"
                if not job.current_step:
                    job.current_step = "intake"
                store.save_job(job)
            logger.info(f"Worker started job: {job_id}")
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
                    mask_subtitle=mask_subtitle,
                    tts_enabled=tts_enabled,
                    subtitles_enabled=subtitles_enabled,
                    subtitle_cover_mode=subtitle_cover_mode,
                    subtitle_bg_opacity=subtitle_bg_opacity,
                    subtitle_mask_padding_x=subtitle_mask_padding_x,
                    subtitle_mask_padding_y=subtitle_mask_padding_y,
                    ocr_sample_interval_sec=ocr_sample_interval_sec,
                    ocr_crop_bottom_ratio=ocr_crop_bottom_ratio,
                ))
                
                # Pipeline handles all exports and cleanup directly now
                pass
            finally:
                loop.close()
    except Exception as e:
        logger.error(f"Error running pipeline in thread for {job_id}: {e}")
    finally:
        set_current_job_id(None)
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
    if job and (job.status in {"queued", "processing", "rendering", "running"} or job_id in running_jobs):
        return {"job_id": job_id, "status": job.status, "message": "Job is already queued or running"}

    if not job:
        job = runner.create_job(str(input_path) if not is_url else input_video, job_id)
    
    config_snapshot = req.config_snapshot or req.model_dump(exclude={"config_snapshot"})
    if req.selected_outputs:
        config_snapshot["selected_outputs"] = req.selected_outputs
    job.status = "queued"
    job.current_step = "intake"
    job.channel_folder = req.channel_folder
    job.platform_folder = req.platform_folder
    job.channel_id = req.channel_id
    job.ocr_only_mode = req.ocr_only_mode
    job.target_language = req.target_language
    job.target_locale = req.target_locale
    job.translation_mode = req.translation_mode
    job.config_snapshot = config_snapshot
    job.steps.setdefault("subtitle_layout", "pending")
    for step in job.steps:
        job.steps[step] = "pending"
    job.errors = []
    store.save_job(job)
    with open(store.get_job_dir(job_id) / "job_config.json", "w", encoding="utf-8") as f:
        json.dump(config_snapshot, f, indent=2, ensure_ascii=False)

    logger.info(f"Created job: {job_id}")
    logger.info(f"Work dir: {store.get_job_dir(job_id) / 'work'}")
    enqueue_pipeline_job(job, args=(
        job_id, req.tone, req.voice, req.rate, req.pitch, req.bgm, resolve_logo_path(req.logo, req.channel_id), req.mask,
        req.tts_enabled, req.subtitles_enabled,
        req.subtitle_cover_mode, req.subtitle_bg_opacity, req.subtitle_mask_padding_x,
        req.subtitle_mask_padding_y, req.ocr_sample_interval_sec, req.ocr_crop_bottom_ratio
    ))

    return {"job_id": job_id, "status": "queued", "message": "Job queued successfully"}

@app.get("/api/jobs/{job_id}/preview-video")
def get_preview_video(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    work_dir = job_work_dir(job)
    candidates = sorted(work_dir.glob("input.*"))
    if not candidates:
        raise HTTPException(status_code=404, detail="Preview video is not ready yet")
    return FileResponse(candidates[0])

@app.get("/api/jobs/{job_id}/logo")
def get_job_logo(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    snapshot = job.config_snapshot or {}
    logo_path = resolve_logo_path(snapshot.get("logo"), snapshot.get("channel_id") or job.channel_id)
    if not logo_path or not logo_path.exists() or not logo_path.is_file():
        raise HTTPException(status_code=404, detail="Logo not found")
    return FileResponse(logo_path)

@app.post("/api/jobs/{job_id}/subtitle-layout")
async def save_subtitle_layout(job_id: str, req: SubtitleLayoutRequest):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.job_id in running_jobs:
        raise HTTPException(status_code=400, detail="Job is still running. Wait until subtitle layout step.")

    normalized = _save_subtitle_layout_snapshot(job, req)
    snapshot = dict(job.config_snapshot or {})
    
    job.steps.setdefault("subtitle_layout", "pending")
    job.steps["subtitle_layout"] = "completed"
    job.steps["render"] = "pending"
    job.steps["metadata"] = "pending"
    job.status = "queued"
    job.current_step = "render"
    job.errors = []
    store.save_job(job)

    logo_path = resolve_logo_path(snapshot.get("logo"), snapshot.get("channel_id"))

    enqueue_pipeline_job(job, args=(
        job_id,
        snapshot.get("tone", "review_phim"),
        snapshot.get("voice", settings.default_voice),
        snapshot.get("rate", settings.default_rate),
        snapshot.get("pitch", settings.default_pitch),
        snapshot.get("bgm") or None,
        logo_path,
        bool(snapshot.get("mask", True)),
        bool(snapshot.get("tts_enabled", True)),
        bool(snapshot.get("subtitles_enabled", True)),
        "text_box_only",
        float(snapshot.get("subtitle_bg_opacity", req.subtitle_bg_opacity)),
        int(snapshot.get("subtitle_mask_padding_x", settings.subtitle_mask_padding_x)),
        int(snapshot.get("subtitle_mask_padding_y", settings.subtitle_mask_padding_y)),
        float(snapshot.get("ocr_sample_interval_sec", settings.ocr_sample_interval_sec)),
        float(snapshot.get("ocr_crop_bottom_ratio", settings.ocr_crop_bottom_ratio)),
    ))
    return {"status": "rendering", "message": "Subtitle layout saved. Final render started.", "layout": normalized["layout"]}

@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job_id in running_jobs:
        return {"status": job.status, "message": "Job is already queued or running"}
        
    # Allow resuming from failed or cancelled status
    if job.status not in {"failed", "cancelled", "processing", "created", "queued"}:
        raise HTTPException(status_code=400, detail=f"Job status '{job.status}' cannot be resumed")
        
    pipeline_steps_order = ["intake", "analyze", "extract_audio", "transcribe", "translate", "tts", "mix_audio", "subtitle_layout", "render", "metadata"]
    first_non_completed = None
    
    if not job.steps:
        job.steps = {}
        
    for step in pipeline_steps_order:
        status = job.steps.get(step, "pending")
        if status in {"failed", "pending", "processing"}:
            job.steps[step] = "pending"
            if first_non_completed is None:
                first_non_completed = step
        elif status == "completed" and first_non_completed is not None:
            job.steps[step] = "pending"

    if first_non_completed is None:
        first_non_completed = "intake"
        job.steps["intake"] = "pending"

    job.status = "queued"
    job.current_step = first_non_completed
    job.errors = []
    store.save_job(job)
    
    enqueue_pipeline_job(job)
    return {"status": "queued", "message": f"Job {job_id} resumed from step {first_non_completed}"}

@app.post("/api/jobs/{job_id}/rerender-subtitle-layout")
def rerender_subtitle_layout(job_id: str, req: SubtitleLayoutRequest):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job_id in running_jobs:
        raise HTTPException(status_code=400, detail="Job is currently running")

    work_dir = job_work_dir(job)
    output_dir = job_output_dir(job)
    output_dir.mkdir(parents=True, exist_ok=True)

    normalized = _save_subtitle_layout_snapshot(job, req)
    snapshot = dict(job.config_snapshot or {})

    try:
        dest_candidates = sorted(work_dir.glob("input.*"))
        if not dest_candidates:
            raise HTTPException(status_code=404, detail="Source video artifact not found")
        dest_video = dest_candidates[0]

        audio_path = work_dir / "mixed_audio.wav"
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail="Mixed audio artifact not found")

        metadata_path = work_dir / "metadata.json"
        if not metadata_path.exists():
            raise HTTPException(status_code=404, detail="Metadata artifact not found")
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        output_srt = work_dir / "output.srt"
        segments = store.load_translated(job_id)
        if segments:
            import pysrt
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
        elif not output_srt.exists():
            raise HTTPException(status_code=404, detail="Translated subtitle artifact not found")

        logo_path = resolve_logo_path(snapshot.get("logo"), snapshot.get("channel_id"))
        
        asset_path = None
        asset = snapshot.get("asset")
        if asset:
            asset_path = resolve_logo_path(asset, snapshot.get("channel_id"))

        # Resolve format target specs
        selected_outputs = snapshot.get("selected_outputs") or []
        if not selected_outputs:
            selected_outputs = ["fb_reels"]

        job.status = "running"
        job.current_step = "render"
        job.steps.setdefault("subtitle_layout", "completed")
        job.steps["subtitle_layout"] = "completed"
        job.steps["render"] = "pending"
        store.save_job(job)
        running_jobs.add(job_id)

        # Resolve Page/Completed export folder
        channel_id = snapshot.get("channel_id") or job.channel_id
        completed_dir = None
        if channel_id and channel_id != "default":
            channels = load_channels_data()
            chan = next((c for c in channels if c.get("id") == channel_id), None)
            if chan:
                chan_name = chan.get("name", "UnknownChannel")
                chan_path = chan.get("path", "").strip()
                if chan_path:
                    p = Path(chan_path)
                    if not p.is_absolute():
                        p = PROJECT_ROOT / p
                    completed_dir = p / job_id
                else:
                    completed_dir = PROJECT_ROOT / "outputs" / chan_name / job_id
                    
        if not completed_dir:
            if settings.default_export_path:
                completed_dir = Path(settings.default_export_path) / job_id
            else:
                completed_dir = PROJECT_ROOT / "outputs" / "Completed" / job_id
                
        completed_dir.mkdir(parents=True, exist_ok=True)

        # Loop through all selected formats and render
        for out in selected_outputs:
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

            temp_video = output_dir / f"temp_{filename}"
            if temp_video.exists():
                temp_video.unlink(missing_ok=True)

            runner.render_service.render(
                video_path=dest_video,
                audio_path=audio_path,
                srt_path=output_srt,
                output_path=temp_video,
                metadata=metadata,
                logo_path=logo_path,
                mask_subtitle=bool(snapshot.get("mask", True)),
                render_subtitles=bool(snapshot.get("subtitles_enabled", True)),
                subtitle_layout=snapshot.get(f"{out}_subtitle_layout") or normalized["layout"],
                subtitle_style=snapshot.get("subtitle_style", "default"),
                subtitle_cover_mode="text_box_only",
                subtitle_bg_opacity=normalized["opacity"],
                w_out=w_out,
                h_out=h_out,
                reframe_mode=reframe_mode,
                crop_layout=crop_layout,
                logo_position=snapshot.get("logo_position", "top_left"),
                logo_layout=snapshot.get("logo_layout"),
                asset_path=asset_path,
                asset_layout=snapshot.get("asset_layout"),
                blur_masks=snapshot.get("blur_masks", [])
            )

            # Move to export directory
            dest_video_path = completed_dir / filename
            if dest_video_path.exists():
                dest_video_path.unlink()
            import shutil
            shutil.move(str(temp_video), str(dest_video_path))

            # Reference the exported video path in job outputs
            if out not in job.outputs:
                from datetime import datetime
                job.outputs[out] = {
                    "output_type": out,
                    "width": w_out,
                    "height": h_out,
                    "duration": metadata.get("duration", 0),
                    "created_at": datetime.utcnow().isoformat()
                }
            job.outputs[out]["file_path"] = str(dest_video_path.resolve())
            job.outputs[out]["render_status"] = "completed"

            if not job.output_path or out == selected_outputs[0]:
                job.output_path = str(dest_video_path.resolve())

        # Copy srt files to export dir if they exist
        input_srt = work_dir / "input.srt"
        if input_srt.exists():
            shutil.copy2(input_srt, completed_dir / "input.srt")
        if output_srt.exists():
            shutil.copy2(output_srt, completed_dir / "output.srt")

        # Delete intermediate output folder in projects directory
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)

        job = store.load_job(job_id) or job
        job.status = "completed"
        job.current_step = "metadata"
        job.steps["render"] = "completed"
        job.steps["metadata"] = "completed"
        store.save_job(job)
        return {"status": "completed", "message": "Video re-rendered with new subtitle layout", "layout": normalized["layout"]}
    except HTTPException:
        raise
    except Exception as e:
        job.status = "failed"
        job.errors.append(f"Subtitle layout re-render failed: {e}")
        store.save_job(job)
        raise HTTPException(status_code=500, detail=f"Subtitle layout re-render failed: {e}")
    finally:
        running_jobs.discard(job_id)

@app.get("/api/jobs")
def list_jobs():
    jobs = []
    if PROJECTS_DIR.exists():
        for item in PROJECTS_DIR.iterdir():
            if item.is_dir():
                state_file = item / "job_state.json"
                if state_file.exists():
                    try:
                        data = read_json(state_file)
                        if data.get("job_id") in running_jobs and data.get("status") in {"created", "", None}:
                            data["status"] = "queued"
                        jobs.append(enrich_job_data(data))
                    except Exception as e:
                        logger.error(f"Error loading state from {state_file}: {e}")
    jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jobs

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.job_id in running_jobs and job.status in {"created", "", None}:
        job.status = "queued"
    return enrich_job_data(job.model_dump())

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
        # Save key re-run settings overrides to snapshot
        snapshot = job.config_snapshot or {}
        snapshot["reverse_video"] = req.reverse_video
        job.config_snapshot = snapshot

        job.steps["tts"] = "pending"
        job.steps["mix_audio"] = "pending"
        job.steps["render"] = "pending"
        job.steps["metadata"] = "pending"
        job.status = "queued"
        job.current_step = "tts"
        job.errors = []
        store.save_job(job)
        
        logo_path = None
        if req.logo:
            overlay_path = PROJECT_ROOT / "examples" / "overlay" / req.logo
            if overlay_path.exists() and overlay_path.is_file():
                logo_path = overlay_path
            else:
                logo_path = Path(req.logo)
                if not logo_path.is_absolute():
                    logo_path = PROJECT_ROOT / logo_path

        enqueue_pipeline_job(job, args=(
            job_id, req.tone, req.voice, req.rate, req.pitch, req.bgm, logo_path, req.mask,
            req.tts_enabled, req.subtitles_enabled,
            req.subtitle_cover_mode, req.subtitle_bg_opacity, req.subtitle_mask_padding_x,
            req.subtitle_mask_padding_y, req.ocr_sample_interval_sec, req.ocr_crop_bottom_ratio
        ))
        return {"status": "re-running", "message": "Transcript saved and pipeline restarted from TTS step"}
        
    return {"status": "saved", "message": "Transcript saved successfully"}

@app.get("/api/jobs/{job_id}/video")
def get_video(job_id: str, output_type: Optional[str] = None):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if output_type and output_type in job.outputs:
        file_path = job.outputs[output_type].get("file_path")
    else:
        file_path = job.output_path
        
    if not file_path:
        raise HTTPException(status_code=404, detail="Job output path not found")
        
    video_path = Path(file_path)
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

class OpenExplorerRequest(BaseModel):
    job_id: Optional[str] = None

@app.post("/api/outputs/open")
def open_outputs_folder(req: Optional[OpenExplorerRequest] = None):
    try:
        import sys
        path = PROJECT_ROOT / "outputs"
        path.mkdir(parents=True, exist_ok=True)
        
        target_path = path.resolve()
        
        # If job_id is provided, resolve the copied final video path inside outputs/
        if req and req.job_id:
            job = store.load_job(req.job_id)
            if job and job.output_path:
                src_video = Path(job.output_path)
                safe_stem = re.sub(r'[^a-zA-Z0-9_ -]', '_', src_video.parent.name.replace("job_", "").replace("job_url_", ""))
                
                # Check target output folder: either channel folder or Completed
                out_dir = PROJECT_ROOT / "outputs" / "Completed"
                if settings.default_export_path:
                    out_dir = Path(settings.default_export_path)
                    
                if job.channel_id:
                    channels = load_channels_data()
                    current_chan = next((c for c in channels if c["id"] == job.channel_id), None)
                    if current_chan:
                        out_dir = resolve_channel_path(current_chan.get("name", "UnknownChannel"), current_chan.get("path"))
                
                # Check job subfolder first
                job_dir = out_dir / req.job_id
                dest_video = None
                for filename in [f"{safe_stem}_vietnam.mp4", "fb_reels_9x16.mp4", "yt_shorts_9x16.mp4", "yt_video_16x9.mp4"]:
                    test_path = job_dir / filename
                    if test_path.exists():
                        dest_video = test_path
                        break
                        
                # Fallback to parent dir for old jobs
                if not dest_video:
                    dest_video = out_dir / f"{safe_stem}_vietnam.mp4"
                    if not dest_video.exists():
                        dest_video = None
                        
                if dest_video and dest_video.exists():
                    target_path = dest_video.resolve()
                    if sys.platform == "win32":
                        import subprocess
                        # Highlights the file inside Windows Explorer
                        subprocess.run(["explorer.exe", "/select,", str(target_path)])
                        return {"status": "success", "message": f"Đã mở và chọn file: {target_path.name}"}
                elif job_dir.exists():
                    target_path = job_dir.resolve()
        
        if sys.platform == "win32":
            os.startfile(str(target_path))
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", str(target_path)])
        else:
            import subprocess
            subprocess.run(["xdg-open", str(target_path)])
            
        return {"status": "success", "message": f"Đã mở thư mục: {target_path}"}
    except Exception as e:
        logger.error(f"Failed to open folder: {e}")
        raise HTTPException(status_code=500, detail=f"Không thể mở thư mục: {str(e)}")

# Channel Schema & Endpoints
class ChannelCreate(BaseModel):
    name: str
    path: str
    tone: Optional[str] = "review_phim"
    voice: Optional[str] = None
    rate: Optional[str] = None
    pitch: Optional[str] = None
    bgm: Optional[str] = None
    logo: Optional[str] = None
    mask: Optional[bool] = True

class ChannelUpdate(BaseModel):
    name: str
    path: str
    tone: Optional[str] = "review_phim"
    voice: Optional[str] = None
    rate: Optional[str] = None
    pitch: Optional[str] = None
    bgm: Optional[str] = None
    logo: Optional[str] = None
    mask: Optional[bool] = True

class PublishRequest(BaseModel):
    channel_id: str

CHANNELS_JSON = PROJECTS_DIR / "channels.json"

def load_channels_data() -> list:
    defaults = [
        {
            "id": "chan_cat",
            "name": "Con mèo",
            "path": str((PROJECT_ROOT / "outputs" / "Con mèo").resolve()),
            "tone": "review_phim",
            "voice": settings.default_voice,
            "rate": settings.default_rate,
            "pitch": settings.default_pitch,
            "bgm": "",
            "logo": "",
            "mask": True
        },
        {
            "id": "chan_review",
            "name": "Review phim TikTok Trung Quốc",
            "path": str((PROJECT_ROOT / "outputs" / "Review phim TikTok Trung Quốc").resolve()),
            "tone": "review_phim",
            "voice": settings.default_voice,
            "rate": settings.default_rate,
            "pitch": settings.default_pitch,
            "bgm": "",
            "logo": "",
            "mask": True
        }
    ]
    if not CHANNELS_JSON.exists():
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(CHANNELS_JSON, "w", encoding="utf-8") as f:
                json.dump(defaults, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save default channels: {e}")
        return defaults
    try:
        with open(CHANNELS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read channels: {e}")
        return []

def save_channels_data(channels: list):
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHANNELS_JSON, "w", encoding="utf-8") as f:
        json.dump(channels, f, indent=4, ensure_ascii=False)

def resolve_channel_path(chan_name: str, chan_path: Optional[str]) -> Path:
    if not chan_path or not chan_path.strip():
        return PROJECT_ROOT / "outputs" / chan_name
    p = Path(chan_path.strip())
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p

@app.get("/api/channels")
def get_channels():
    channels = load_channels_data()
    for chan in channels:
        if not chan.get("path"):
            chan["path"] = f"outputs/{chan.get('name', 'UnknownChannel')}"
        # Auto-create directory on disk if missing
        try:
            p = resolve_channel_path(chan.get("name", "UnknownChannel"), chan.get("path"))
            p.mkdir(parents=True, exist_ok=True)
            (p / "assets").mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to auto-create channel directory: {e}")
    return channels

@app.post("/api/channels")
def create_channel(req: ChannelCreate):
    channels = load_channels_data()
    import uuid
    new_id = f"chan_{uuid.uuid4().hex[:8]}"
    
    p = resolve_channel_path(req.name, req.path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        (p / "assets").mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create directory: {e}")

    new_chan = {
        "id": new_id,
        "name": req.name,
        "path": req.path.strip(),
        "tone": req.tone,
        "voice": req.voice,
        "rate": req.rate,
        "pitch": req.pitch,
        "bgm": req.bgm,
        "logo": req.logo,
        "mask": req.mask
    }
    channels.append(new_chan)
    save_channels_data(channels)
    return new_chan

@app.put("/api/channels/{id}")
def update_channel(id: str, req: ChannelUpdate):
    channels = load_channels_data()
    for chan in channels:
        if chan["id"] == id:
            chan["name"] = req.name
            chan["path"] = req.path.strip()
            chan["tone"] = req.tone
            chan["voice"] = req.voice
            chan["rate"] = req.rate
            chan["pitch"] = req.pitch
            chan["bgm"] = req.bgm
            chan["logo"] = req.logo
            chan["mask"] = req.mask
            
            p = resolve_channel_path(req.name, req.path)
            try:
                p.mkdir(parents=True, exist_ok=True)
                (p / "assets").mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create directory: {e}")
                
            save_channels_data(channels)
            return chan
    raise HTTPException(status_code=404, detail="Channel not found")

@app.delete("/api/channels/{id}")
def delete_channel(id: str):
    channels = load_channels_data()
    filtered = [c for c in channels if c["id"] != id]
    if len(filtered) == len(channels):
        raise HTTPException(status_code=404, detail="Channel not found")
    save_channels_data(filtered)
    return {"status": "ok"}

@app.post("/api/channels/{id}/open")
def open_channel_folder(id: str):
    channels = load_channels_data()
    chan = next((c for c in channels if c["id"] == id), None)
    if not chan:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    p = resolve_channel_path(chan.get("name", "UnknownChannel"), chan.get("path"))
    p.mkdir(parents=True, exist_ok=True)
    
    if sys.platform == "win32":
        os.startfile(str(p.resolve()))
    elif sys.platform == "darwin":
        import subprocess
        subprocess.run(["open", str(p.resolve())])
    else:
        import subprocess
        subprocess.run(["xdg-open", str(p.resolve())])
        
    return {"status": "success", "message": f"Đã mở thư mục kênh: {chan.get('name')}"}



@app.post("/api/jobs/{job_id}/publish")
def publish_job_to_channel(job_id: str, req: PublishRequest):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        target_channel = None if req.channel_id == "default" else req.channel_id
        job.channel_id = target_channel
        if job.config_snapshot is not None:
            job.config_snapshot["channel_id"] = target_channel
        store.save_job(job)
        return {
            "status": "success",
            "channel_id": job.channel_id,
            "moved_files": []
        }

    src_video_path = Path(job.output_path)
    safe_stem = re.sub(r'[^a-zA-Z0-9_ -]', '_', src_video_path.parent.name.replace("job_", "").replace("job_url_", ""))

    default_dir = PROJECT_ROOT / "outputs" / "Completed"
    current_dir = default_dir / job_id
    channels = load_channels_data()

    if job.channel_id:
        current_chan = next((c for c in channels if c["id"] == job.channel_id), None)
        if current_chan:
            current_dir = resolve_channel_path(current_chan.get("name", "UnknownChannel"), current_chan.get("path")) / job_id

    target_channel_id = req.channel_id
    if target_channel_id == "default":
        target_dir = default_dir / job_id
    else:
        target_chan = next((c for c in channels if c["id"] == target_channel_id), None)
        if not target_chan:
            raise HTTPException(status_code=404, detail="Target channel not found")
        target_dir = resolve_channel_path(target_chan.get("name", "UnknownChannel"), target_chan.get("path")) / job_id

    target_dir.mkdir(parents=True, exist_ok=True)
    moved_files = []

    # 1. New style: Job subfolder exists
    if current_dir.exists() and current_dir.is_dir():
        for item in current_dir.iterdir():
            if item.is_file():
                dest_file = target_dir / item.name
                if dest_file.exists():
                    try:
                        dest_file.unlink()
                    except Exception as ex:
                        logger.error(f"Failed to delete existing file: {ex}")
                import shutil
                try:
                    shutil.move(str(item), str(dest_file))
                    moved_files.append(item.name)
                except Exception as ex:
                    logger.error(f"Failed to move file {item.name}: {ex}")
        # Clean up old empty subfolder
        if current_dir != target_dir:
            try:
                current_dir.rmdir()
            except Exception:
                pass
    else:
        # 2. Fallback: Old style files in the parent directory
        parent_current = current_dir.parent
        parent_target = target_dir.parent
        parent_target.mkdir(parents=True, exist_ok=True)
        if parent_current.exists():
            for item in parent_current.iterdir():
                if item.is_file() and (item.name.startswith(safe_stem) or item.name.startswith(f"job_{safe_stem}") or item.name.startswith(job_id)):
                    dest_file = parent_target / item.name
                    if dest_file.exists():
                        try:
                            dest_file.unlink()
                        except Exception as ex:
                            logger.error(f"Failed to delete existing file: {ex}")
                    import shutil
                    try:
                        shutil.move(str(item), str(dest_file))
                        moved_files.append(item.name)
                    except Exception as ex:
                        logger.error(f"Failed to move file {item.name}: {ex}")

    job.channel_id = None if target_channel_id == "default" else target_channel_id
    store.save_job(job)

    return {
        "status": "success",
        "channel_id": job.channel_id,
        "moved_files": moved_files
    }

@app.get("/api/jobs/{job_id}/path")
def get_job_file_path(job_id: str, type: str = "video"):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.output_path:
        raise HTTPException(status_code=400, detail="Job output path is missing")
        
    src_video_path = Path(job.output_path)
    safe_stem = re.sub(r'[^a-zA-Z0-9_ -]', '_', src_video_path.parent.name.replace("job_", "").replace("job_url_", ""))
    
    default_dir = PROJECT_ROOT / "outputs" / "Completed"
    current_dir = default_dir / job_id
    
    if job.channel_id:
        channels = load_channels_data()
        current_chan = next((c for c in channels if c["id"] == job.channel_id), None)
        if current_chan:
            current_dir = resolve_channel_path(current_chan.get("name", "UnknownChannel"), current_chan.get("path")) / job_id
            
    if type == "folder":
        # Return subfolder if it exists, otherwise parent folder
        if current_dir.exists():
            return {"path": str(current_dir.resolve())}
        return {"path": str(current_dir.parent.resolve())}
    else:
        # Check subfolder first
        for name in [f"{safe_stem}_vietnam.mp4", "fb_reels_9x16.mp4", "yt_shorts_9x16.mp4", "yt_video_16x9.mp4"]:
            test_path = current_dir / name
            if test_path.exists():
                return {"path": str(test_path.resolve())}
                
        # Fallback to parent dir for old jobs
        parent_dir = current_dir.parent
        for name in [f"{safe_stem}_vietnam.mp4", f"{job_id}_fb_reels_9x16.mp4", f"{job_id}_yt_shorts_9x16.mp4", f"{job_id}_yt_video_16x9.mp4"]:
            test_path = parent_dir / name
            if test_path.exists():
                return {"path": str(test_path.resolve())}
                
        # Ultimate fallback
        video_file = current_dir / f"{safe_stem}_vietnam.mp4"
        return {"path": str(video_file.resolve())}

@app.get("/api/jobs/{job_id}/download")
def download_job_video(job_id: str):
    res = get_job_file_path(job_id, type="video")
    path = Path(res["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=path.name, media_type="video/mp4")

class OpenLocalPathRequest(BaseModel):
    path: str

@app.post("/api/media/open")
def open_local_path(req: OpenLocalPathRequest):
    try:
        import sys
        p = Path(req.path)
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"Không tìm thấy đường dẫn: {req.path}")
            
        target_path = p.resolve()
        if sys.platform == "win32":
            os.startfile(str(target_path))
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", str(target_path)])
        else:
            import subprocess
            subprocess.run(["xdg-open", str(target_path)])
            
        return {"status": "success", "message": f"Đã mở thư mục: {target_path}"}
    except Exception as e:
        logger.error(f"Failed to open local path: {e}")
        raise HTTPException(status_code=500, detail=f"Không thể mở thư mục: {str(e)}")

@app.post("/api/media/browse")
def browse_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        # Hide tkinter root window
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True) # Focus dialog
        
        folder_path = filedialog.askdirectory(title="Chọn thư mục chứa video đầu vào")
        root.destroy()
        
        if folder_path:
            return {"status": "success", "path": os.path.normpath(folder_path)}
        return {"status": "cancelled", "path": None}
    except Exception as e:
        logger.error(f"Failed to browse folder: {e}")
        raise HTTPException(status_code=500, detail=f"Không thể mở hộp thoại chọn thư mục: {str(e)}")

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
    # Free running list if active
    if job_id in running_jobs:
        running_jobs.discard(job_id)
        
    job_dir = store.get_job_dir(job_id)
    state_file = job_dir / "job_state.json"
    
    # 1. Delete exported files in outputs/ if they exist
    try:
        job = store.load_job(job_id)
        if job:
            # Determine potential export dirs
            export_dirs = []
            
            # Default export dir
            default_dir = PROJECT_ROOT / "outputs" / "Completed"
            if settings.default_export_path:
                default_dir = Path(settings.default_export_path)
            export_dirs.append(default_dir / job_id)
            
            # Channel export dirs (published / config)
            channels = load_channels_data()
            if job.channel_id:
                chan = next((c for c in channels if c["id"] == job.channel_id), None)
                if chan:
                    chan_dir = resolve_channel_path(chan.get("name", "UnknownChannel"), chan.get("path"))
                    export_dirs.append(chan_dir / job_id)
                    
            # Check all channels to be sure
            for chan in channels:
                chan_dir = resolve_channel_path(chan.get("name", "UnknownChannel"), chan.get("path"))
                export_dirs.append(chan_dir / job_id)
                
            # Clean up resolved directories
            for out_dir in export_dirs:
                if out_dir.exists() and out_dir.is_dir():
                    logger.info(f"Deleting exported job directory: {out_dir}")
                    import shutil
                    try:
                        shutil.rmtree(out_dir)
                    except Exception as ex:
                        logger.error(f"Failed to delete exported job folder {out_dir}: {ex}")
                        
            # Clean up old-style flat files in parent folders
            src_video_path = Path(job.output_path) if job.output_path else None
            if src_video_path:
                safe_stem = re.sub(r'[^a-zA-Z0-9_ -]', '_', src_video_path.parent.name.replace("job_", "").replace("job_url_", ""))
                
                # Check Completed root
                parent_completed = default_dir
                if parent_completed.exists():
                    for item in parent_completed.iterdir():
                        if item.is_file() and (item.name.startswith(safe_stem) or item.name.startswith(f"job_{safe_stem}") or item.name.startswith(job_id)):
                            try:
                                item.unlink()
                            except Exception:
                                pass
                                
                # Check channel roots
                for chan in channels:
                    chan_dir = resolve_channel_path(chan.get("name", "UnknownChannel"), chan.get("path"))
                    if chan_dir.exists():
                        for item in chan_dir.iterdir():
                            if item.is_file() and (item.name.startswith(safe_stem) or item.name.startswith(f"job_{safe_stem}") or item.name.startswith(job_id)):
                                try:
                                    item.unlink()
                                except Exception:
                                    pass
    except Exception as e:
        logger.error(f"Error during exported files deletion: {e}")

    # 2. Delete state file first to make it disappear from UI instantly
    if state_file.exists():
        try:
            state_file.unlink()
        except Exception:
            pass
            
    # 3. Try to clean up the directory (fails silently if locked on Windows, which is safe)
    if job_dir.exists():
        import shutil
        try:
            shutil.rmtree(job_dir)
        except Exception:
            pass
            
    return {"status": "deleted", "message": f"Job {job_id} has been deleted successfully"}

@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
    if job_id in running_jobs:
        # Mark as failed in store immediately
        job.status = "failed"
        job.errors.append("Bị ngắt bởi người dùng.")
        store.save_job(job)
        
        # Discard from running_jobs so UI knows it's stopped
        running_jobs.discard(job_id)
        return {"status": "cancelled", "message": f"Job {job_id} has been cancelled"}
@app.post("/api/jobs/{job_id}/rerun")
def rerun_job(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
    if job_id in running_jobs:
        raise HTTPException(status_code=400, detail="Job is currently running and cannot be restarted")
        
    # Reset job state to intake step
    job.status = "queued"
    job.current_step = "intake"
    if job.steps:
        for step in job.steps:
            job.steps[step] = "pending"
    else:
        job.steps = {"intake": "pending"}
    job.errors = []
    store.save_job(job)
    
    # Run the pipeline runner
    enqueue_pipeline_job(job)
    return {"status": "queued", "message": f"Job {job_id} has been restarted successfully"}


@app.get("/api/jobs/{job_id}/logs")
def get_job_logs(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    log_file = store.get_job_dir(job_id) / "run.log"
    if not log_file.exists() or log_file.stat().st_size == 0:
        lines = [
            f"Job: {job.job_id}",
            f"Trạng thái: {job.status}",
            f"Bước hiện tại: {job.current_step or 'không có'}",
            ""
        ]
        step_names = {
            "intake": "1. Tải / Nhập video",
            "analyze": "2. Phân tích khung hình",
            "extract_audio": "3. Tách âm thanh gốc",
            "transcribe": "4. Nhận diện giọng nói (ASR)",
            "translate": "5. Dịch thuật phụ đề (AI)",
            "tts": "6. Sinh giọng nói mới (TTS)",
            "mix_audio": "7. Trộn âm thanh & nhạc nền",
            "render": "8. Render video dọc 9:16",
            "metadata": "9. Tiêu đề & HashTags (AI)",
        }
        for step, name in step_names.items():
            lines.append(f"{name}: {job.steps.get(step, 'pending')}")

        transcript = store.load_transcript(job_id)
        translated = store.load_translated(job_id)
        if transcript:
            lines.append("")
            lines.append(f"Bước 4: đã nhận diện/import {len(transcript)} câu thoại.")
        if translated:
            lines.append(f"Bước 5: đã dịch {len(translated)} câu thoại.")
            tts_done = sum(1 for segment in translated if segment.tts_path)
            if tts_done:
                lines.append(f"Bước 6: đã tạo giọng đọc {tts_done}/{len(translated)} câu.")
        if job.errors:
            lines.append("")
            lines.append("Lỗi:")
            lines.extend(job.errors)
        return {"logs": "\n".join(lines)}

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        return {"logs": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {e}")

def list_logos() -> list:
    overlay_dir = PROJECT_ROOT / "examples" / "overlay"
    if not overlay_dir.exists():
        return []
    extensions = (".png", ".jpg", ".jpeg")
    files = [f.name for f in overlay_dir.iterdir() if f.is_file() and f.name.lower().endswith(extensions)]
    return sorted(files)

@app.get("/api/config")
def get_global_config():
    return {
        "voices": AVAILABLE_VOICES,
        "tones": AVAILABLE_TONES,
        "rates": AVAILABLE_RATES,
        "pitches": AVAILABLE_PITCHES,
        "logos": list_logos(),
        "presets": EMOTION_PRESETS,
        "defaults": {
            "tone": "review_phim",
            "voice": settings.default_voice or "vi-VN-HoaiMyNeural",
            "rate": settings.default_rate or "+0%",
            "pitch": settings.default_pitch or "+0Hz",
            "bgm": "",
            "logo": "",
            "subtitle_cover_mode": settings.subtitle_cover_mode or "text_box_only",
            "subtitle_bg_opacity": settings.subtitle_bg_opacity or 0.20,
            "subtitle_mask_padding_x": settings.subtitle_mask_padding_x or 20,
            "subtitle_mask_padding_y": settings.subtitle_mask_padding_y or 12,
            "ocr_sample_interval_sec": settings.ocr_sample_interval_sec or 0.75,
            "ocr_crop_bottom_ratio": settings.ocr_crop_bottom_ratio or 0.45,
            "tts_enabled": True,
            "subtitles_enabled": True,
            "mask": True,
            "ocr_only_mode": False,
            "target_language": settings.default_target_language or "vi-VN",
            "target_locale": "",
            "translation_mode": settings.default_translation_mode or "natural",
            "selected_outputs": ["fb_reels", "yt_shorts"]
        }
    }

class KeysSaveRequest(BaseModel):
    key: str
    key2: Optional[str] = ""
    key3: Optional[str] = ""
    key4: Optional[str] = ""
    key5: Optional[str] = ""
    key6: Optional[str] = ""
    key7: Optional[str] = ""
    key8: Optional[str] = ""
    key9: Optional[str] = ""
    key10: Optional[str] = ""

@app.get("/api/config/key-check")
def check_api_key():
    is_set = bool(settings.gemini_api_key.strip() or os.environ.get("GEMINI_API_KEY", "").strip())
    res = {
        "configured": is_set,
        "gemini_api_key": settings.gemini_api_key,
        "default_export_path": settings.default_export_path,
    }
    for i in range(2, 11):
        res[f"gemini_api_key_{i}"] = getattr(settings, f"gemini_api_key_{i}", "")
    return res

@app.get("/api/config/key-status")
def check_keys_status():
    results = {}
    for i in range(1, 11):
        key_name = "gemini_api_key" if i == 1 else f"gemini_api_key_{i}"
        key_val = getattr(settings, key_name, "").strip()
        if not key_val:
            results[f"key_{i}"] = "chua_cau_hinh"
            continue
            
        try:
            from google import genai
            client = genai.Client(api_key=key_val)
            # Make a cheap API call to list models with page_size=1
            client.models.list(config={"page_size": 1})
            results[f"key_{i}"] = "hoat_dong"
        except Exception as e:
            err_msg = str(e).lower()
            if "quota" in err_msg or "429" in err_msg or "exhausted" in err_msg:
                results[f"key_{i}"] = "het_quota"
            elif "invalid" in err_msg or "not authorized" in err_msg or "key not valid" in err_msg or "api_key_invalid" in err_msg:
                results[f"key_{i}"] = "khong_hop_le"
            else:
                results[f"key_{i}"] = f"loi: {str(e)[:40]}"
    return results

@app.post("/api/config/save-key")
def save_api_keys(req: KeysSaveRequest):
    key = req.key.strip()
    keys_list = [key]
    for i in range(2, 11):
        keys_list.append((getattr(req, f"key{i}", "") or "").strip())
    
    if not key:
        raise HTTPException(status_code=400, detail="API Key chính không được để trống")
        
    env_path = PROJECT_ROOT / ".env"
    try:
        def update_env_var(content_str, name, val):
            if f"{name}=" in content_str:
                lines = content_str.splitlines()
                for i, line in enumerate(lines):
                    if line.strip().startswith(f"{name}="):
                        lines[i] = f"{name}={val}"
                        break
                return "\n".join(lines) + "\n"
            else:
                return content_str.rstrip() + f"\n{name}={val}\n"

        content = ""
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            example_path = PROJECT_ROOT / ".env.example"
            if example_path.exists():
                import shutil
                shutil.copy2(example_path, env_path)
                with open(env_path, "r", encoding="utf-8") as f:
                    content = f.read()

        content = update_env_var(content, "GEMINI_API_KEY", keys_list[0])
        for i in range(2, 11):
            content = update_env_var(content, f"GEMINI_API_KEY_{i}", keys_list[i-1])

        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        # Update settings in-memory
        settings.gemini_api_key = keys_list[0]
        os.environ["GEMINI_API_KEY"] = keys_list[0]
        for i in range(2, 11):
            setattr(settings, f"gemini_api_key_{i}", keys_list[i-1])
            os.environ[f"GEMINI_API_KEY_{i}"] = keys_list[i-1]
        
        # Update PipelineRunner's translator keys in memory
        if hasattr(runner, "translator") and runner.translator:
            runner.translator.api_keys = [k for k in keys_list if k]
            from google import genai
            try:
                runner.translator.client = genai.Client(api_key=keys_list[0])
            except Exception as e:
                logger.warning(f"Failed to update translator client: {e}")
                
        return {"status": "success", "message": "Đã lưu cấu hình API Key thành công!"}
    except Exception as e:
        logger.error(f"Failed to save API keys to .env: {e}")
        raise HTTPException(status_code=500, detail=f"Không thể ghi key vào file .env: {str(e)}")

class ExportPathSaveRequest(BaseModel):
    default_export_path: str

@app.post("/api/config/save-export-path")
def save_export_path(req: ExportPathSaveRequest):
    export_path = req.default_export_path.strip()
    env_path = PROJECT_ROOT / ".env"
    try:
        def update_env_var(content_str, name, val):
            if f"{name}=" in content_str:
                lines = content_str.splitlines()
                for i, line in enumerate(lines):
                    if line.strip().startswith(f"{name}="):
                        lines[i] = f"{name}={val}"
                        break
                return "\n".join(lines) + "\n"
            else:
                return content_str.rstrip() + f"\n{name}={val}\n"

        content = ""
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            example_path = PROJECT_ROOT / ".env.example"
            if example_path.exists():
                import shutil
                shutil.copy2(example_path, env_path)
                with open(env_path, "r", encoding="utf-8") as f:
                    content = f.read()

        content = update_env_var(content, "DEFAULT_EXPORT_PATH", export_path)

        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        # Update settings in-memory
        settings.default_export_path = export_path
        os.environ["DEFAULT_EXPORT_PATH"] = export_path
        
        return {"status": "success", "message": "Đã lưu đường dẫn Export thành công!"}
    except Exception as e:
        logger.error(f"Failed to save default export path: {e}")
        raise HTTPException(status_code=500, detail=f"Không thể lưu đường dẫn: {str(e)}")

@app.get("/api/assets/list")
def list_global_assets():
    assets = []
    global_dir = PROJECT_ROOT / "examples" / "overlay"
    if global_dir.exists():
        for f in global_dir.iterdir():
            if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                assets.append(f.name)
    return sorted(list(set(assets)))

@app.post("/api/jobs/{job_id}/toggle-published")
def toggle_job_published(job_id: str):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.is_published = not job.is_published
    store.save_job(job)
    return {"status": "success", "is_published": job.is_published}

# Pages API (Page CRUD Aliases)
PageCreate = ChannelCreate
PageUpdate = ChannelUpdate

@app.get("/api/pages")
def get_pages():
    return get_channels()

@app.post("/api/pages")
def create_page(req: PageCreate):
    return create_channel(req)

@app.put("/api/pages/{id}")
def update_page(id: str, req: PageUpdate):
    return update_channel(id, req)

@app.delete("/api/pages/{id}")
def delete_page(id: str):
    return delete_channel(id)

@app.post("/api/pages/{id}/open")
def open_page_folder_alias(id: str):
    return open_channel_folder(id)

class BgmDownloadRequest(BaseModel):
    url: str
    filename: str

@app.get("/api/music")
def list_bgm_files():
    music_dir = PROJECT_ROOT / "examples" / "music"
    if not music_dir.exists():
        return []
    extensions = (".mp3", ".wav", ".m4a")
    files = [f.name for f in music_dir.iterdir() if f.is_file() and f.name.lower().endswith(extensions)]
    return sorted(files)

@app.post("/api/music/download")
def download_bgm_track(req: BgmDownloadRequest):
    music_dir = PROJECT_ROOT / "examples" / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    
    filename = req.filename.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Filename cannot be empty")
    
    filename = os.path.basename(filename)
    if not filename.lower().endswith((".mp3", ".wav", ".m4a")):
        filename += ".mp3"
        
    dest_path = music_dir / filename
    
    import urllib.request
    import shutil
    
    try:
        req_headers = urllib.request.Request(
            req.url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req_headers) as response, open(dest_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return {"status": "success", "message": f"Tải thành công nhạc nền và lưu thành {filename}!"}
    except Exception as e:
        logger.error(f"Failed to download BGM: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khi tải tệp từ URL: {str(e)}")

import re
import urllib.request
import urllib.parse
import json
import yt_dlp

HTML_RE = re.compile('<[^<]+?>')

def search_youtube(query: str, limit: int = 12):
    ydl_opts = {
        'extract_flat': True,
        'skip_download': True,
        'quiet': True,
    }
    videos = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            if res and "entries" in res:
                for entry in res["entries"]:
                    if not entry:
                        continue
                    dur_sec = entry.get("duration")
                    duration_str = "00:00"
                    if dur_sec:
                        minutes = int(dur_sec // 60)
                        seconds = int(dur_sec % 60)
                        duration_str = f"{minutes:02d}:{seconds:02d}"
                        
                    view_count = entry.get("view_count") or 0
                    view_str = f"{view_count:,}" if view_count else "N/A"
                    
                    thumbnail = ""
                    if entry.get("thumbnails"):
                        thumbnail = entry["thumbnails"][-1]["url"]
                    elif entry.get("thumbnail"):
                        thumbnail = entry["thumbnail"]
                        
                    url = entry.get("url")
                    if not url and entry.get("id"):
                        url = f"https://www.youtube.com/watch?v={entry['id']}"
                        
                    videos.append({
                        "title": entry.get("title", "No Title"),
                        "url": url,
                        "thumbnail": thumbnail,
                        "duration": duration_str,
                        "views": view_str,
                        "source": "youtube"
                    })
    except Exception as e:
        logger.error(f"YouTube search error: {e}")
    return videos

def translate_query_to_chinese(query: str) -> str:
    # Check if query already has Chinese characters
    if any(u'\u4e00' <= char <= u'\u9fff' for char in query):
        return query
    
    try:
        from app.providers.llm_translate_provider import LLMTranslateProvider
        provider = LLMTranslateProvider()
        if provider.api_keys:
            prompt = f"Translate the following search keyword from Vietnamese to natural, common Chinese search terms used on Bilibili. Return ONLY the translated Chinese keyword, no other text or explanation: {query}"
            response = provider.generate_content(prompt=prompt)
            translated = response.text.strip().strip('"').strip("'").strip()
            logger.info(f"Translated query '{query}' to Chinese: '{translated}'")
            return translated
    except Exception as e:
        logger.error(f"Failed to translate query to Chinese: {e}")
    return query

def search_bilibili(query: str, limit: int = 12):
    videos = []
    try:
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword={encoded_query}&page=1"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://search.bilibili.com/",
            "Cookie": "buvid3=INFOCARD-A1B2C3D4E5F6G7H8I9J0;"
        }
        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 0 and data.get("data") and data["data"].get("result"):
                results = data["data"]["result"]
                for entry in results[:limit]:
                    title_clean = HTML_RE.sub('', entry.get("title", ""))
                    duration_str = entry.get("duration", "00:00")
                    
                    view_count = entry.get("play") or 0
                    view_str = str(view_count)
                    if isinstance(view_count, int):
                        if view_count >= 10000:
                            view_str = f"{round(view_count / 10000, 1)} vạn"
                        else:
                            view_str = f"{view_count}"
                            
                    thumbnail = entry.get("pic", "")
                    if thumbnail and thumbnail.startswith("//"):
                        thumbnail = "https:" + thumbnail
                        
                    url = entry.get("arcurl")
                    if not url and entry.get("bvid"):
                        url = f"https://www.bilibili.com/video/{entry['bvid']}"
                        
                    videos.append({
                        "title": title_clean,
                        "url": url,
                        "thumbnail": thumbnail,
                        "duration": duration_str,
                        "views": view_str,
                        "source": "bilibili"
                    })
    except Exception as e:
        logger.error(f"Bilibili search error: {e}")
    return videos

def search_douyin(query: str, limit: int = 12):
    videos = []
    cookie_file_path = PROJECTS_DIR / "cookies.txt"
    if not cookie_file_path.exists():
        cookie_file_path = PROJECT_ROOT / "cookies.txt"
        
    import urllib.parse
    import re
    from playwright.sync_api import sync_playwright
    
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.douyin.com/search/{encoded_query}?type=video"
    
    # Try direct search on Douyin first
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    headless=True,
                    channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"]
                )
            except Exception:
                try:
                    browser = p.chromium.launch(
                        headless=True,
                        channel="msedge",
                        args=["--disable-blink-features=AutomationControlled"]
                    )
                except Exception:
                    browser = p.chromium.launch(
                        headless=True,
                        args=["--disable-blink-features=AutomationControlled"]
                    )
                    
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720}
            )
            
            from app.services.downloader import _load_cookies_from_file
            cookie_jar = _load_cookies_from_file(cookie_file_path)
            playwright_cookies = []
            for c in cookie_jar:
                p_cookie = {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path,
                    "secure": c.secure,
                }
                if c.expires and isinstance(c.expires, (int, float)) and c.expires > 0:
                    p_cookie["expires"] = float(c.expires)
                playwright_cookies.append(p_cookie)
                
            if playwright_cookies:
                context.add_cookies(playwright_cookies)
                
            page = context.new_page()
            # Bypass webdriver check
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            try:
                page.wait_for_selector('a[href*="/video/"]', timeout=12000)
            except Exception:
                pass
            
            page_title = page.title() or ""
            logger.info(f"Direct Douyin Search page title: {page_title}")
            if "验证" not in page_title and "安全" not in page_title:
                links = page.locator('a[href*="/video/"]').all()
                seen_ids = set()
                for link in links:
                    if len(videos) >= limit:
                        break
                    href = link.get_attribute("href") or ""
                    if not href:
                        continue
                    
                    if "douyin.com" not in href:
                        full_url = "https://www.douyin.com" + href
                    else:
                        if href.startswith("//"):
                            full_url = "https:" + href
                        else:
                            full_url = href
                            
                    video_id_match = re.search(r'/video/(\d+)', full_url)
                    if not video_id_match:
                        continue
                    video_id = video_id_match.group(1)
                    if video_id in seen_ids:
                        continue
                    seen_ids.add(video_id)
                    
                    img = link.locator('img').first
                    thumbnail = ""
                    title = ""
                    if img.count() > 0:
                        thumbnail = img.get_attribute("src") or ""
                        title = img.get_attribute("alt") or ""
                    
                    if thumbnail and thumbnail.startswith("//"):
                        thumbnail = "https:" + thumbnail
                    
                    if not title:
                        title = link.text_content() or ""
                        title = title.strip()
                        
                    if not title:
                        title = f"Video Douyin {video_id}"
                    
                    duration = "00:00"
                    time_spans = link.locator('span').all()
                    for span in time_spans:
                        txt = span.text_content() or ""
                        if re.match(r'^\d+:\d+$', txt.strip()) or re.match(r'^\d+:\d+:\d+$', txt.strip()):
                            duration = txt.strip()
                            break
                            
                    videos.append({
                        "title": title,
                        "url": full_url,
                        "thumbnail": thumbnail,
                        "duration": duration,
                        "views": "N/A",
                        "source": "douyin"
                    })
            browser.close()
    except Exception as e:
        logger.error(f"Direct Douyin search error: {e}")
        
    # Fallback to Bing Search site:douyin.com/video search if direct search yielded no videos
    if not videos:
        logger.info(f"Direct Douyin search returned 0 results. Falling back to Bing site:douyin.com search for '{query}'...")
        try:
            import urllib.request
            import urllib.parse
            import re
            
            bing_url = f"https://www.bing.com/search?q=site:douyin.com/video+{encoded_query}"
            
            req = urllib.request.Request(
                bing_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
                }
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8', errors='ignore')
                
            # Clean up html escape entities
            html_clean = html.replace("&amp;", "&")
            
            # Find all a tags containing douyin.com/video
            matches = re.findall(r'<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>', html_clean, re.DOTALL)
            seen_ids = set()
            for href, title_html in matches:
                if len(videos) >= limit:
                    break
                    
                # Check if it contains douyin.com/video
                if "douyin.com/video" not in href and "douyin.com%2Fvideo" not in href:
                    continue
                    
                clean_url = href.split("?")[0]
                if "/video/" not in clean_url:
                    continue
                    
                video_id_match = re.search(r'/video/(\d+)', clean_url)
                if not video_id_match:
                    continue
                video_id = video_id_match.group(1)
                if video_id in seen_ids:
                    continue
                seen_ids.add(video_id)
                
                # Clean html tags from title
                title = re.sub(r'<[^>]+>', '', title_html).strip()
                title = title.replace(" - 抖音", "").replace(" - Douyin", "").strip()
                
                videos.append({
                    "title": title or f"Video Douyin {video_id}",
                    "url": clean_url,
                    "thumbnail": "https://sf3-cdn-tos.douyinstatic.com/obj/eden-cn/pipehvjtbps/douyin_logo.ssl.png",
                    "duration": "00:00",
                    "views": "N/A",
                    "source": "douyin"
                })
        except Exception as ge:
            logger.error(f"Bing fallback search error: {ge}")
            
    # Final Fallback to Bilibili search for "抖音 {query}" if direct and Bing searches returned 0 videos
    if not videos:
        logger.info(f"Direct and Bing searches for Douyin returned 0 results. Falling back to Bilibili search for '抖音 {query}'...")
        try:
            bilibili_query = f"抖音 {query}"
            videos = search_bilibili(bilibili_query, limit)
            for v in videos:
                v["source"] = "bilibili"
        except Exception as bbe:
            logger.error(f"Bilibili fallback search for Douyin failed: {bbe}")
            
    return videos

@app.get("/api/media/search")
def search_media(q: str, source: str = "youtube", limit: int = 12):
    if not q:
        return {"videos": [], "translated_query": None}
    
    translated_q = q
    if source == "bilibili":
        translated_q = translate_query_to_chinese(q)
        videos = search_bilibili(translated_q, limit)
    elif source == "douyin":
        translated_q = translate_query_to_chinese(q)
        videos = search_douyin(translated_q, limit)
    else:
        videos = search_youtube(q, limit)
        
    return {
        "videos": videos,
        "translated_query": translated_q if translated_q != q else None
    }

@app.get("/api/debug_douyin_search")
def debug_douyin_search(q: str):
    import urllib.parse
    import re
    from playwright.sync_api import sync_playwright
    import tempfile
    
    result = {
        "status": "started",
        "query": q,
        "translated": None,
        "page_title": None,
        "links_found": 0,
        "screenshot_saved": False,
        "screenshot_path": None,
        "error": None,
        "videos": []
    }
    
    try:
        translated_q = translate_query_to_chinese(q)
        result["translated"] = translated_q
        
        cookie_file_path = PROJECTS_DIR / "cookies.txt"
        if not cookie_file_path.exists():
            cookie_file_path = PROJECT_ROOT / "cookies.txt"
            
        encoded_query = urllib.parse.quote(translated_q)
        url = f"https://www.douyin.com/search/{encoded_query}?type=video"
        result["search_url"] = url
        
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=False, channel="chrome")
            except Exception as e:
                try:
                    browser = p.chromium.launch(headless=False, channel="msedge")
                except Exception as e:
                    browser = p.chromium.launch(headless=False)
                    
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
            
            from app.services.downloader import _load_cookies_from_file
            cookie_jar = _load_cookies_from_file(cookie_file_path)
            playwright_cookies = []
            for c in cookie_jar:
                p_cookie = {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path,
                    "secure": c.secure,
                }
                if c.expires and isinstance(c.expires, (int, float)) and c.expires > 0:
                    p_cookie["expires"] = float(c.expires)
                playwright_cookies.append(p_cookie)
                
            if playwright_cookies:
                context.add_cookies(playwright_cookies)
                result["cookies_loaded"] = len(playwright_cookies)
                
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector('a[href*="/video/"]', timeout=20000)
            except Exception:
                pass
            
            result["page_title"] = page.title()
            
            debug_path = Path(tempfile.gettempdir()) / "douyin_search_debug.png"
            page.screenshot(path=str(debug_path))
            result["screenshot_saved"] = True
            result["screenshot_path"] = str(debug_path)
            
            links = page.locator('a[href*="/video/"]').all()
            result["links_found"] = len(links)
            
            seen_ids = set()
            for link in links:
                href = link.get_attribute("href") or ""
                if not href:
                    continue
                
                if "douyin.com" not in href:
                    full_url = "https://www.douyin.com" + href
                else:
                    if href.startswith("//"):
                        full_url = "https:" + href
                    else:
                        full_url = href
                        
                video_id_match = re.search(r'/video/(\d+)', full_url)
                if not video_id_match:
                    continue
                video_id = video_id_match.group(1)
                if video_id in seen_ids:
                    continue
                seen_ids.add(video_id)
                
                img = link.locator('img').first
                thumbnail = ""
                title = ""
                if img.count() > 0:
                    thumbnail = img.get_attribute("src") or ""
                    title = img.get_attribute("alt") or ""
                
                if not title:
                    title = link.text_content() or ""
                    title = title.strip()
                
                duration = "00:00"
                time_spans = link.locator('span').all()
                for span in time_spans:
                    txt = span.text_content() or ""
                    if re.match(r'^\d+:\d+$', txt.strip()) or re.match(r'^\d+:\d+:\d+$', txt.strip()):
                        duration = txt.strip()
                        break
                        
                result["videos"].append({
                    "title": title,
                    "url": full_url,
                    "thumbnail": thumbnail,
                    "duration": duration
                })
                
            browser.close()
            result["status"] = "success"
            
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        import traceback
        result["traceback"] = traceback.format_exc()
        
    return result



@app.get("/api/voices")
def get_voices():
    return AVAILABLE_VOICES



@app.get("/")


def read_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Frontend Static SPA index.html is missing. Please create it.</h1>")
    return FileResponse(index_path)

class CropConfigRequest(BaseModel):
    output_type: str
    reframe_mode: str
    crop_x_percent: float
    crop_y_percent: float
    crop_width_percent: float
    crop_height_percent: float

@app.post("/api/jobs/{job_id}/crop")
def update_job_crop_config(job_id: str, req: CropConfigRequest):
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    snapshot = job.config_snapshot or {}
    snapshot[f"{req.output_type}_reframe_mode"] = req.reframe_mode
    snapshot[f"{req.output_type}_crop"] = {
        "crop_x_percent": req.crop_x_percent,
        "crop_y_percent": req.crop_y_percent,
        "crop_width_percent": req.crop_width_percent,
        "crop_height_percent": req.crop_height_percent
    }
    job.config_snapshot = snapshot
    store.save_job(job)
    
    with open(store.get_job_dir(job_id) / "job_config.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
        
    return {"status": "success", "message": "Đã lưu toạ độ crop thành công!"}

@app.post("/api/jobs/{job_id}/render-output")
async def trigger_render_output(job_id: str, req: Dict[str, Any]):
    output_type = req.get("output_type")
    if not output_type:
        raise HTTPException(status_code=400, detail="Missing output_type")
        
    job = store.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if job.job_id in running_jobs:
        raise HTTPException(status_code=400, detail="Cannot render while job is running")
        
    snapshot = job.config_snapshot or {}
    selected_outputs = snapshot.get("selected_outputs", [])
    
    if output_type == "all":
        for out in selected_outputs:
            if out in job.outputs:
                job.outputs[out]["render_status"] = "pending"
    else:
        if output_type not in selected_outputs:
            selected_outputs.append(output_type)
            snapshot["selected_outputs"] = selected_outputs
            job.config_snapshot = snapshot
            
        from datetime import datetime
        if output_type in job.outputs:
            job.outputs[output_type]["render_status"] = "pending"
        else:
            job.outputs[output_type] = {
                "output_type": output_type,
                "file_path": "",
                "width": 1920 if output_type == "yt_video" else 1080,
                "height": 1080 if output_type == "yt_video" else 1920,
                "duration": job.outputs.get(selected_outputs[0], {}).get("duration", 0) if selected_outputs else 0,
                "render_status": "pending",
                "upload_status": "pending",
                "created_at": datetime.utcnow().isoformat()
            }
            
    job.steps["render"] = "pending"
    job.status = "queued"
    job.current_step = "render"
    job.errors = []
    store.save_job(job)
    
    logo_path = resolve_logo_path(snapshot.get("logo"), snapshot.get("channel_id"))
    enqueue_pipeline_job(job, args=(
        job_id, snapshot.get("tone", "review_phim"), snapshot.get("voice", settings.default_voice),
        snapshot.get("rate", "+0%"), snapshot.get("pitch", "+0Hz"), snapshot.get("bgm"), logo_path,
        snapshot.get("mask", True), snapshot.get("tts_enabled", True), snapshot.get("subtitles_enabled", True),
        snapshot.get("subtitle_cover_mode", settings.subtitle_cover_mode),
        snapshot.get("subtitle_bg_opacity", settings.subtitle_bg_opacity),
        snapshot.get("subtitle_mask_padding_x", settings.subtitle_mask_padding_x),
        snapshot.get("subtitle_mask_padding_y", settings.subtitle_mask_padding_y),
        snapshot.get("ocr_sample_interval_sec", settings.ocr_sample_interval_sec),
        snapshot.get("ocr_crop_bottom_ratio", settings.ocr_crop_bottom_ratio)
    ))
    
    return {"status": "success", "message": f"Rendering for {output_type} triggered in background."}

@app.post("/api/logo/upload")
async def upload_logo_file(file: UploadFile = File(...)):
    overlay_dir = PROJECT_ROOT / "examples" / "overlay"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    
    filename = os.path.basename(file.filename)
    if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Only PNG, JPG, or JPEG images are allowed.")
        
    dest_path = overlay_dir / filename
    try:
        with open(dest_path, "wb") as buffer:
            import shutil
            shutil.copyfileobj(file.file, buffer)
        return {"status": "success", "message": f"Tải lên logo {filename} thành công!"}
    except Exception as e:
        logger.error(f"Failed to upload logo: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khi lưu logo: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    import subprocess
    import sys
    
    # Self-healing: Free port 8088 if occupied to prevent WinError 10013
    if sys.platform == "win32":
        try:
            output = subprocess.check_output("netstat -aon | findstr :8088", shell=True).decode()
            for line in output.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[1].endswith(":8088"):
                    pid = parts[-1]
                    if int(pid) != os.getpid():
                        subprocess.run(f"taskkill /f /pid {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    uvicorn.run("app.server:app", host="127.0.0.1", port=8088, reload=True)


