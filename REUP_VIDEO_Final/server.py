"""
FastAPI Backend Server cho Reup Video Douyin
- REST API: check URL, start processing, download
- WebSocket: real-time progress updates
- Static files: serve frontend
"""

import os
import uuid
import json
import asyncio
import logging
import uvicorn
from pathlib import Path
from typing import Dict, Optional, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import pipeline
import tts_manager

# ============================================
# Setup
# ============================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Reup Video Douyin", version="1.0.0")

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active tasks and WebSocket connections
tasks: Dict[str, dict] = {}
ws_connections: Dict[str, list] = {}

BASE_DIR = Path(__file__).parent


# ============================================
# Request/Response Models
# ============================================
class CheckUrlRequest(BaseModel):
    url: str


class ProcessRequest(BaseModel):
    url: str
    translate: bool = True
    subtitle: bool = True
    voiceover: bool = True
    watermark: bool = True
    keep_audio: bool = False  # Keep original audio, skip voiceover
    keep_bgm: bool = False  # Extract and keep BGM
    voice: str = "edge_female"  # Key from TTS_VOICES registry
    gemini_api_key: Optional[list[str]] = None
    auto_render: bool = False  # If False, stops before rendering so user can review/edit subtitles


# ============================================
# WebSocket Connection Manager
# ============================================
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, list[WebSocket]] = {}

    async def connect(self, task_id: str, websocket: WebSocket):
        await websocket.accept()
        if task_id not in self.connections:
            self.connections[task_id] = []
        self.connections[task_id].append(websocket)
        logger.info(f"WebSocket connected for task {task_id}")

    def disconnect(self, task_id: str, websocket: WebSocket):
        if task_id in self.connections:
            if websocket in self.connections[task_id]:
                self.connections[task_id].remove(websocket)
            if not self.connections[task_id]:
                del self.connections[task_id]
        logger.info(f"WebSocket disconnected for task {task_id}")

    async def send_progress(self, task_id: str, data: dict):
        if task_id in self.connections:
            dead = []
            for ws in self.connections[task_id]:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.connections[task_id].remove(ws)


manager = ConnectionManager()


# ============================================
# API Endpoints
# ============================================
@app.post("/api/check-url")
async def check_url(req: CheckUrlRequest):
    """Validate Douyin URL and extract video info."""
    url = req.url.strip()

    if not url:
        raise HTTPException(400, "URL không được để trống")

    # Validate URL pattern - accept all common Douyin formats
    import re
    patterns = [
        r"^https?://(www\.)?douyin\.com/video/\d+",
        r"^https?://v\.douyin\.com/",
        r"^https?://(www\.)?douyin\.com/note/\d+",
        r"^https?://(www\.)?douyin\.com/discover",
        r"^https?://(www\.)?douyin\.com/jingxuan",
        r"^https?://(www\.)?douyin\.com/.*modal_id=\d+",
        r"^https?://(www\.)?douyin\.com/share/",
        r"^https?://(www\.)?douyin\.com/user/",
        r"^https?://www\.iesdouyin\.com",
        r"^https?://(www\.)?tiktok\.com/",
        r"^https?://vm\.tiktok\.com/",
        r"^https?://(www\.)?douyin\.com/",  # Fallback: any douyin.com URL
    ]
    if not any(re.match(p, url, re.I) for p in patterns):
        raise HTTPException(400, "Link không hợp lệ. Vui lòng dán link Douyin.")

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, pipeline.get_video_info, url)
        return JSONResponse({"status": "ok", "data": info})
    except Exception as e:
        err_str = str(e)
        logger.exception("Error checking URL")
        if "Fresh cookies" in err_str or "cookie" in err_str.lower():
            raise HTTPException(400,
                "Douyin yêu cầu cookies. Hãy xuất cookies.txt từ Chrome:\n"
                "1. Cài extension 'Get cookies.txt LOCALLY' trên Chrome\n"
                "2. Vào douyin.com → click extension → Export\n"
                "3. Lưu file cookies.txt vào thư mục REUP VIDEO"
            )
        raise HTTPException(500, f"Không thể lấy thông tin video: {err_str}")


@app.get("/api/tts-engines")
async def get_tts_engines():
    """Get list of available TTS engines and their voices."""
    engines = tts_manager.get_available_engines()
    return JSONResponse({"status": "ok", "engines": engines})


@app.get("/api/tts-preview/{voice_key}")
async def preview_tts_voice(voice_key: str):
    """Generate a short audio preview for a TTS voice."""
    voice_info = tts_manager.get_voice_info(voice_key)
    engine = voice_info["engine"]

    if not tts_manager.check_engine_available(engine):
        raise HTTPException(400, f"Engine {engine} chưa được cài đặt. {tts_manager.get_install_instructions(engine)}")

    # Generate preview audio
    preview_dir = BASE_DIR / "temp" / "_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_file = preview_dir / f"preview_{voice_key}.mp3"

    # Use cached preview if exists and recent (< 1 hour)
    import time
    if preview_file.exists():
        age = time.time() - preview_file.stat().st_mtime
        if age < 3600:
            return FileResponse(str(preview_file), media_type="audio/mpeg")

    sample_text = "Xin chào! Đây là giọng đọc mẫu. Bạn có thể nghe thử chất lượng giọng nói trước khi chọn."

    try:
        success = await pipeline._generate_tts_segment(
            sample_text, engine, voice_info["voice_id"], preview_file
        )
        if success and preview_file.exists():
            return FileResponse(str(preview_file), media_type="audio/mpeg")
        else:
            raise HTTPException(500, "Không thể tạo audio mẫu")
    except Exception as e:
        logger.error(f"TTS preview error: {e}")
        raise HTTPException(500, f"Lỗi tạo preview: {str(e)}")


@app.post("/api/process")
async def start_process(req: ProcessRequest):
    """Start the video processing pipeline."""
    task_id = str(uuid.uuid4())[:8]

    options = {
        "translate": req.translate,
        "subtitle": req.subtitle,
        "voiceover": False if req.keep_audio else req.voiceover,
        "watermark": req.watermark,
        "keep_audio": req.keep_audio,
        "keep_bgm": req.keep_bgm,
        "voice": req.voice,
        "gemini_api_key": req.gemini_api_key
    }
    logger.info(f"[DEBUG] Process options: {options}")

    tasks[task_id] = {
        "status": "queued",
        "url": req.url,
        "options": options,
        "progress": 0,
        "message": "Đang chuẩn bị...",
    }

    # Start processing in background
    asyncio.create_task(_run_task(task_id, req.url, options))

    return JSONResponse({
        "status": "ok",
        "task_id": task_id,
        "message": "Đã bắt đầu xử lý"
    })


async def _run_task(task_id: str, url: str, options: dict):
    """Run pipeline and push progress via WebSocket."""
    logger.info(f"[DEBUG] _run_task options: {options}")

    # Calculate step weights based on selected options
    step_names = ["download"]
    if options.get("watermark"):
        step_names.append("watermark")
    if options.get("translate") or options.get("subtitle"):
        step_names.append("transcribe")
    if options.get("translate"):
        step_names.append("translate")
    if options.get("voiceover"):
        step_names.append("voiceover")
    step_names.append("render")

    step_weight = 100.0 / len(step_names)
    step_index = {name: i for i, name in enumerate(step_names)}

    async def progress_callback(step: str, percent: int, message: str):
        """Send progress to WebSocket clients."""
        idx = step_index.get(step, 0)
        overall = int(idx * step_weight + (percent / 100.0) * step_weight)
        overall = min(overall, 100)

        tasks[task_id].update({
            "status": "processing",
            "step": step,
            "step_percent": percent,
            "progress": overall,
            "message": message,
        })

        await manager.send_progress(task_id, {
            "type": "progress",
            "task_id": task_id,
            "step": step,
            "step_percent": percent,
            "progress": overall,
            "message": message,
        })

    try:
        result = await pipeline.run_pipeline(task_id, url, options, progress_callback)

        if result.get("status") == "error":
            tasks[task_id].update({
                "status": "error",
                "progress": 0,
                "message": result.get("error", "Lỗi không xác định"),
            })
            await manager.send_progress(task_id, {
                "type": "error",
                "task_id": task_id,
                "message": result.get("error", "Lỗi không xác định"),
            })
        else:
            tasks[task_id].update({
                "status": "completed",
                "progress": 100,
                "message": "Hoàn thành!",
                "result": result,
            })

            await manager.send_progress(task_id, {
                "type": "complete",
                "task_id": task_id,
                "status": "completed",
                "progress": 100,
                "message": "Xử lý hoàn tất!",
                "file_size_mb": result.get("file_size_mb", 0),
            })

    except Exception as e:
        logger.exception(f"Task {task_id} failed")
        tasks[task_id].update({
            "status": "error",
            "progress": 0,
            "message": f"Lỗi: {str(e)}",
        })
        await manager.send_progress(task_id, {
            "type": "error",
            "task_id": task_id,
            "message": f"Lỗi: {str(e)}",
        })


@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    """Get task processing status."""
    if task_id not in tasks:
        raise HTTPException(404, "Task không tồn tại")
    return JSONResponse({"status": "ok", "data": tasks[task_id]})


@app.get("/api/download/{task_id}")
async def download_file(task_id: str):
    """Download the processed video file."""
    if task_id not in tasks:
        raise HTTPException(404, "Task không tồn tại")

    task = tasks[task_id]
    if task.get("status") != "completed":
        raise HTTPException(400, "Video chưa xử lý xong")

    output_path = Path(task.get("result", {}).get("output_path", ""))
    if not output_path.exists():
        raise HTTPException(404, "File không tồn tại")

    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=f"reup_video_{task_id}.mp4",
    )


@app.get("/api/preview/{task_id}")
async def preview_video(task_id: str):
    """Stream the processed video for preview. Falls back to source video."""
    task_dir = BASE_DIR / "temp" / task_id

    if not task_dir.exists():
        raise HTTPException(404, "Task không tồn tại")

    # Try output first, then clean, then original
    import glob
    import os
    outputs = glob.glob(str(task_dir / "output*.mp4"))
    
    candidates = []
    if outputs:
        # Sort outputs by modification time (newest first)
        outputs.sort(key=os.path.getmtime, reverse=True)
        candidates.extend(outputs)
    
    candidates.extend([str(task_dir / "clean.mp4"), str(task_dir / "original.mp4")])

    for video_path_str in candidates:
        video_path = Path(video_path_str)
        if video_path.exists() and video_path.stat().st_size > 1000:
            return FileResponse(
                path=str(video_path),
                media_type="video/mp4",
            )

    raise HTTPException(404, "Không tìm thấy video")


# ============================================
# WebSocket Endpoint
# ============================================
@app.websocket("/ws/progress/{task_id}")
async def websocket_progress(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time progress updates."""
    await manager.connect(task_id, websocket)

    # Send current status if task already exists
    if task_id in tasks:
        try:
            await websocket.send_json({
                "type": "status",
                "task_id": task_id,
                **tasks[task_id],
            })
        except Exception:
            pass

    try:
        while True:
            # Keep connection alive, listen for client messages
            data = await websocket.receive_text()
            # Client can send ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(task_id, websocket)


# ============================================
# Subtitle Editor API Endpoints
# ============================================
class SegmentUpdate(BaseModel):
    segments: list  # list of {start, end, text_zh, text_vi}


class FindReplaceRequest(BaseModel):
    find: str
    replace: str
    case_sensitive: bool = False


class ReRenderRequest(BaseModel):
    margin_v: int = 25
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None


@app.get("/api/segments/{task_id}")
async def get_segments(task_id: str):
    """Get all translated segments with timestamps."""
    task_dir = BASE_DIR / "temp" / task_id

    # Try translated segments first, then original
    vi_path = task_dir / "segments_vi.json"
    zh_path = task_dir / "segments_zh.json"

    if vi_path.exists():
        with open(vi_path, "r", encoding="utf-8") as f:
            segments = json.load(f)
    elif zh_path.exists():
        with open(zh_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            segments = [
                {"start": s["start"], "end": s["end"],
                 "text_zh": s["text"], "text_vi": s["text"]}
                for s in raw
            ]
    else:
        raise HTTPException(404, "Không tìm thấy dữ liệu phụ đề")

    return JSONResponse({"status": "ok", "segments": segments})


@app.put("/api/segments/{task_id}")
async def update_segments(task_id: str, req: SegmentUpdate):
    """Update segments after user edits (text, timing)."""
    task_dir = BASE_DIR / "temp" / task_id
    if not task_dir.exists():
        raise HTTPException(404, "Task không tồn tại")

    # Save updated segments
    vi_path = task_dir / "segments_vi.json"
    with open(vi_path, "w", encoding="utf-8") as f:
        json.dump(req.segments, f, ensure_ascii=False, indent=2)

    return JSONResponse({"status": "ok", "message": f"Đã lưu {len(req.segments)} đoạn"})


@app.post("/api/find-replace/{task_id}")
async def find_replace(task_id: str, req: FindReplaceRequest):
    """Find and replace text in all segments."""
    task_dir = BASE_DIR / "temp" / task_id
    vi_path = task_dir / "segments_vi.json"

    if not vi_path.exists():
        raise HTTPException(404, "Không tìm thấy dữ liệu phụ đề")

    with open(vi_path, "r", encoding="utf-8") as f:
        segments = json.load(f)

    count = 0
    for seg in segments:
        text = seg.get("text_vi", "")
        if req.case_sensitive:
            if req.find in text:
                seg["text_vi"] = text.replace(req.find, req.replace)
                count += 1
        else:
            import re as _re
            if _re.search(_re.escape(req.find), text, _re.IGNORECASE):
                seg["text_vi"] = _re.sub(
                    _re.escape(req.find), req.replace, text, flags=_re.IGNORECASE
                )
                count += 1

    # Save
    with open(vi_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    return JSONResponse({
        "status": "ok",
        "replaced": count,
        "segments": segments,
        "message": f"Đã thay thế {count} đoạn"
    })


@app.get("/api/export/{task_id}/{fmt}")
async def export_segments(task_id: str, fmt: str):
    """Export segments in various formats: srt, json, txt, lines."""
    task_dir = BASE_DIR / "temp" / task_id
    vi_path = task_dir / "segments_vi.json"

    if not vi_path.exists():
        raise HTTPException(404, "Không tìm thấy dữ liệu phụ đề")

    with open(vi_path, "r", encoding="utf-8") as f:
        segments = json.load(f)

    if fmt == "json":
        return JSONResponse(segments)

    elif fmt == "srt":
        lines = []
        for i, seg in enumerate(segments, 1):
            start = _format_srt_time(seg.get("start", 0))
            end = _format_srt_time(seg.get("end", 0))
            text = seg.get("text_vi", "")
            lines.append(f"{i}\n{start} --> {end}\n{text}\n")
        content = "\n".join(lines)
        from fastapi.responses import Response
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=subtitle_{task_id}.srt"}
        )

    elif fmt == "txt":
        texts = [seg.get("text_vi", "") for seg in segments]
        content = "\n".join(texts)
        from fastapi.responses import Response
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=text_{task_id}.txt"}
        )

    elif fmt == "lines":
        lines = []
        for seg in segments:
            start = _format_srt_time(seg.get("start", 0))
            end = _format_srt_time(seg.get("end", 0))
            text = seg.get("text_vi", "")
            lines.append(f"[{start} - {end}] {text}")
        content = "\n".join(lines)
        from fastapi.responses import Response
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=lines_{task_id}.txt"}
        )

    raise HTTPException(400, f"Format không hỗ trợ: {fmt}")


# Track re-render status for polling
render_status: Dict[str, dict] = {}


@app.post("/api/re-render/{task_id}")
async def re_render(task_id: str, req: ReRenderRequest):
    """Re-render video with edited segments (updated subtitles + voiceover)."""
    if task_id not in tasks:
        raise HTTPException(404, "Task không tồn tại")

    task = tasks[task_id]
    task_dir = BASE_DIR / "temp" / task_id
    options = task.get("result", {}).get("options", task.get("options", {}))
    options["margin_v"] = req.margin_v
    if req.pos_x is not None:
        options["pos_x"] = req.pos_x
    if req.pos_y is not None:
        options["pos_y"] = req.pos_y

    # Load updated segments
    vi_path = task_dir / "segments_vi.json"
    if not vi_path.exists():
        raise HTTPException(404, "Không tìm thấy dữ liệu phụ đề")

    with open(vi_path, "r", encoding="utf-8") as f:
        segments = json.load(f)

    # Init status
    render_status[task_id] = {
        "status": "running",
        "progress": 0,
        "message": "Đang bắt đầu render..."
    }

    async def do_re_render():
        async def progress_cb(step, pct, msg):
            render_status[task_id] = {
                "status": "running",
                "progress": pct,
                "message": msg
            }

        try:
            # Re-generate voiceover with edited text
            if options.get("voiceover", True):
                voice = options.get("voice", "female")
                await pipeline.step_voiceover(
                    task_dir, segments, voice, progress_cb
                )

            # Re-render
            await pipeline.step_render(task_dir, segments, options, progress_cb)

            output = task_dir / "output.mp4"
            file_size_mb = 0
            if output.exists():
                task.setdefault("result", {})
                task["result"]["output_path"] = str(output)
                task["result"]["file_size"] = output.stat().st_size
                file_size_mb = round(output.stat().st_size / (1024 * 1024), 1)
                task["result"]["file_size_mb"] = file_size_mb

            render_status[task_id] = {
                "status": "complete",
                "progress": 100,
                "message": "Đã render lại video!",
                "file_size_mb": file_size_mb
            }
        except Exception as e:
            logger.error(f"Re-render error: {e}")
            render_status[task_id] = {
                "status": "error",
                "progress": 0,
                "message": f"Lỗi render: {str(e)}"
            }

    asyncio.create_task(do_re_render())

    return JSONResponse({
        "status": "ok",
        "message": "Đang render lại video với nội dung đã chỉnh sửa..."
    })


@app.get("/api/re-render-status/{task_id}")
async def re_render_status(task_id: str):
    """Poll re-render status."""
    status = render_status.get(task_id, {"status": "unknown", "message": "Không tìm thấy"})
    return JSONResponse(status)


def _format_srt_time(seconds) -> str:
    """Convert seconds to SRT format."""
    seconds = float(seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ============================================
# Static Files (Frontend)
# ============================================
# Serve index.html at root
@app.get("/")
async def serve_root():
    return FileResponse(str(BASE_DIR / "index.html"))


# Serve other static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ============================================
# Startup
# ============================================
@app.on_event("startup")
async def startup():
    # Create temp directory
    temp_dir = BASE_DIR / "temp"
    temp_dir.mkdir(exist_ok=True)
    logger.info("🚀 Reup Video Douyin server started!")
    logger.info("📱 Mở http://localhost:8000 trên trình duyệt")


# ============================================
# Run
# ============================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
