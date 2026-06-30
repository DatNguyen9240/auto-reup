"""
Pipeline xử lý video Douyin → Việt hóa
6 bước: Download → Watermark → STT → Translate → TTS → Render
"""

import os
import re
import json
import asyncio
import subprocess
import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ============================================
# CONSTANTS
# ============================================
TEMP_DIR = Path(__file__).parent / "temp"
FFMPEG_PATH = "ffmpeg"  # Will be in PATH after install

# Voice config is now in tts_manager.py
from tts_manager import TTS_VOICES, get_voice_info, check_engine_available

SUBTITLE_STYLE = (
    "FontName=Arial,FontSize=20,Bold=1,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,BackColour=&H00000000,"
    "BorderStyle=3,Outline=6,Shadow=0,"
    "MarginV=25,Alignment=2"
)


def normalize_douyin_url(url: str) -> str:
    """Convert various Douyin URL formats to a standard format yt-dlp can handle."""
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    # Handle jingxuan/discover URLs with modal_id parameter
    # e.g. https://www.douyin.com/jingxuan?modal_id=7647094786759865807
    if "modal_id" in query:
        video_id = query["modal_id"][0]
        return f"https://www.douyin.com/video/{video_id}"

    return url


_METADATA_CACHE = {}

def get_douyin_metadata_playwright(url: str) -> dict:
    import urllib.request
    import re
    from playwright.sync_api import sync_playwright

    if url in _METADATA_CACHE:
        return _METADATA_CACHE[url]

    # Resolve short URL first so caching works better
    resolved_url = url
    if 'v.douyin.com' in resolved_url:
        req = urllib.request.Request(resolved_url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resolved_url = resp.url
        except Exception:
            pass

    if resolved_url in _METADATA_CACHE:
        return _METADATA_CACHE[resolved_url]
            
    video_info = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        def handle_response(response):
            nonlocal video_info
            if 'aweme/detail/' in response.url or 'aweme/iteminfo/' in response.url:
                try:
                    data = response.json()
                    aweme = data.get('aweme_detail')
                    if aweme:
                        video_info = {
                            "title": aweme.get('desc', 'Video Douyin'),
                            "duration": aweme.get('video', {}).get('duration', 0) // 1000,
                            "thumbnail": aweme.get('video', {}).get('cover', {}).get('url_list', [''])[0],
                            "play_addr": aweme.get('video', {}).get('play_addr', {}).get('url_list', [''])[0],
                            "view_count": aweme.get('statistics', {}).get('play_count', 0),
                            "like_count": aweme.get('statistics', {}).get('digg_count', 0),
                            "uploader": aweme.get('author', {}).get('nickname', ''),
                        }
                except Exception:
                    pass

        page.on("response", handle_response)
        
        try:
            page.goto(resolved_url, wait_until='domcontentloaded', timeout=15000)
            page.wait_for_timeout(8000)
        except Exception:
            pass
            
        browser.close()

    if not video_info or not video_info.get("play_addr"):
        raise Exception("Không thể lấy thông tin video từ Douyin (Bị chặn hoặc URL không hợp lệ).")
        
    # Cache both original and resolved URLs
    _METADATA_CACHE[url] = video_info
    _METADATA_CACHE[resolved_url] = video_info
    
    return video_info

# ============================================
# STEP 1: Download video from Douyin
# ============================================
async def step_download(task_dir: Path, url: str, progress_cb: Callable) -> dict:
    """Download video from Douyin using Playwright and requests."""
    url = normalize_douyin_url(url)
    await progress_cb("download", 0, "Đang kết nối Douyin...")

    original_path = task_dir / "original.mp4"
    audio_path = task_dir / "audio.wav"

    loop = asyncio.get_event_loop()
    
    await progress_cb("download", 10, "Đang lấy link video gốc (bypass captcha)...")
    info = await loop.run_in_executor(None, get_douyin_metadata_playwright, url)

    await progress_cb("download", 30, "Đang tải video...")
    
    def do_download():
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.douyin.com/'
        }
        with requests.get(info['play_addr'], headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(original_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): 
                    f.write(chunk)
                    
    await loop.run_in_executor(None, do_download)

    await progress_cb("download", 70, "Đang trích xuất audio...")

    # Extract audio for STT
    cmd = [
        FFMPEG_PATH, "-i", str(original_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        "-y", str(audio_path)
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await proc.wait()

    # Get video info
    title = info.get("title", "Video Douyin")
    duration = info.get("duration", 0)
    thumbnail = info.get("thumbnail", "")
    view_count = info.get("view_count", 0)

    await progress_cb("download", 100, "Đã tải video thành công!")

    return {
        "title": title,
        "duration": duration,
        "thumbnail": thumbnail,
        "view_count": view_count,
        "original_path": str(original_path),
        "audio_path": str(audio_path),
    }


# ============================================
# STEP 2: Remove watermark
# ============================================
async def step_remove_watermark(task_dir: Path, progress_cb: Callable) -> str:
    """Remove Douyin watermark using FFmpeg delogo."""
    await progress_cb("watermark", 0, "Đang phân tích vị trí watermark...")

    original = task_dir / "original.mp4"
    clean = task_dir / "clean.mp4"

    # Get video dimensions
    probe_cmd = [
        FFMPEG_PATH, "-i", str(original),
        "-hide_banner"
    ]
    proc = await asyncio.create_subprocess_exec(
        *probe_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    stderr_text = stderr.decode("utf-8", errors="ignore")

    # Parse resolution
    width, height = 1080, 1920  # Default for Douyin vertical videos
    match = re.search(r"(\d{3,4})x(\d{3,4})", stderr_text)
    if match:
        width, height = int(match.group(1)), int(match.group(2))

    await progress_cb("watermark", 30, "Đang xóa watermark Douyin...")

    # Douyin watermarks: top-right logo + bottom username
    # Apply delogo for common positions
    top_x = max(0, width - 180)
    bottom_x = max(0, width // 2 - 100)
    bottom_y = max(0, height - 80)

    vf = (
        f"delogo=x={top_x}:y=10:w=170:h=55,"
        f"delogo=x={bottom_x}:y={bottom_y}:w=200:h=60"
    )

    cmd = [
        FFMPEG_PATH, "-i", str(original),
        "-vf", vf,
        "-c:a", "copy",
        "-y", str(clean)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await proc.wait()

    await progress_cb("watermark", 100, "Đã xóa watermark!")

    # If delogo failed, use original
    if not clean.exists() or clean.stat().st_size < 1000:
        logger.warning("Delogo failed, using original video")
        import shutil
        shutil.copy2(original, clean)

    return str(clean)


# ============================================
# STEP 3: Speech-to-Text (STT)
# ============================================
async def step_transcribe(task_dir: Path, progress_cb: Callable) -> list:
    """Transcribe Chinese audio using faster-whisper."""
    await progress_cb("transcribe", 0, "Đang tải mô hình AI nhận diện giọng nói...")

    audio_path = task_dir / "audio.wav"

    loop = asyncio.get_event_loop()

    def do_transcribe():
        from faster_whisper import WhisperModel

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments_gen, info = model.transcribe(
            str(audio_path),
            language="zh",
            word_timestamps=True,
            vad_filter=True,
        )

        segments = []
        for seg in segments_gen:
            segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
            })

        return segments

    await progress_cb("transcribe", 20, "Đang nhận diện giọng nói tiếng Trung...")
    segments = await loop.run_in_executor(None, do_transcribe)

    if not segments:
        # Fallback: create a single segment if no speech detected
        segments = [{"start": 0, "end": 5, "text": "无法识别语音内容"}]

    await progress_cb("transcribe", 100, f"Đã nhận diện {len(segments)} đoạn!")

    # Save segments for reference
    with open(task_dir / "segments_zh.json", "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    return segments


# ============================================
# STEP 4: Translate Chinese → Vietnamese
# ============================================
async def step_translate(task_dir: Path, segments: list, options: dict, progress_cb: Callable) -> list:
    """Translate Chinese segments to Vietnamese using Gemini context-aware translation, with fallback to deep-translator."""
    await progress_cb("translate", 0, "Đang chuẩn bị dịch sang tiếng Việt...")

    loop = asyncio.get_event_loop()
    used_engine = "Google Translate"

    def do_translate():
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="zh-CN", target="vi")

        # Fallback helper: translates line by line (runs in thread)
        def translate_fallback():
            logger.info("Using deep-translator (fallback/default)")
            translated_segments = []
            total_segs = len(segments)
            for i, seg in enumerate(segments):
                try:
                    if seg["text"].strip():
                        translated_text = translator.translate(seg["text"])
                    else:
                        translated_text = ""
                except Exception as e:
                    logger.warning(f"Translation error for segment {i}: {e}")
                    translated_text = seg["text"]  # Fallback to original
                
                # Update progress roughly every 5 segments or at the end
                if i % 5 == 0 or i == total_segs - 1:
                    percent = 55 + int((i / total_segs) * 20) # Map 0-100% of fallback to 55-75% total progress
                    try:
                        asyncio.run_coroutine_threadsafe(
                            progress_cb("translate", percent, f"Đang dịch dự phòng ({i+1}/{total_segs})..."),
                            loop
                        )
                    except:
                        pass

                translated_segments.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "text_zh": seg["text"],
                    "text_vi": translated_text or seg["text"],
                })
            return translated_segments, "Google Translate"



            # Context-Aware Translation with Gemini
        logger.info("Using Gemini Context-Aware Translation")
        try:
            from google import genai
            
            gemini_keys = options.get("gemini_api_key", [])
            if isinstance(gemini_keys, str):
                gemini_keys = [gemini_keys]
            if not gemini_keys:
                fallback_key = os.getenv("GEMINI_API_KEY")
                if fallback_key:
                    gemini_keys = [fallback_key]
                else:
                    return translate_fallback()

            # Build payload
            lines = []
            for i, seg in enumerate(segments):
                lines.append(f"{i+1}| {seg['text']}")
            full_text = "\n".join(lines)

            prompt = f"""Dưới đây là kịch bản của một video cần được dịch từ tiếng Trung sang tiếng Việt.
Hãy đọc hiểu toàn bộ ngữ cảnh câu chuyện, sau đó dịch từng câu sang tiếng Việt một cách tự nhiên, mượt mà, đúng văn phong nói.
TUYỆT ĐỐI KHÔNG dịch word-by-word.
QUAN TRỌNG NHẤT: BẮT BUỘC dịch thật NGẮN GỌN, XÚC TÍCH. Chọn từ vựng ngắn để tổng thời gian phát âm tiếng Việt không dài hơn tiếng Trung. Lược bỏ các từ thừa nhưng vẫn giữ nguyên ý chính.

QUAN TRỌNG: Bạn BẮT BUỘC phải trả về đúng số dòng tương ứng với bản gốc. Mỗi dòng phải bắt đầu bằng số thứ tự và dấu ngoặc đứng (|) giống hệt bản gốc. Không được gộp hay tách dòng để tránh làm hỏng thời gian phụ đề.

Bản gốc ({len(segments)} dòng):
{full_text}

Bản dịch tiếng Việt ({len(segments)} dòng):"""

            import time
            response = None
            translated_dict = {}
            last_error = None
            
            # API Key Rotation Loop
            for key_idx, current_key in enumerate(gemini_keys):
                if not current_key.strip():
                    continue
                    
                logger.info(f"Using Gemini API Key {key_idx+1}/{len(gemini_keys)}")
                client = genai.Client(api_key=current_key.strip())
                
                success = False
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        model_to_use = 'gemini-flash-lite-latest' if attempt < 2 else 'gemini-flash-latest'
                        logger.info(f"Calling Gemini API (attempt {attempt+1}, model: {model_to_use})...")
                        response = client.models.generate_content(
                            model=model_to_use,
                            contents=prompt,
                        )
                        success = True
                        break # Break retry loop
                    except Exception as e:
                        logger.warning(f"Gemini API attempt {attempt+1} failed: {e}")
                        last_error = e
                        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                            logger.warning(f"API Key {key_idx+1} rate limited. Switching to next key if available.")
                            break # Break retry loop immediately, move to next key
                        
                        if attempt < max_retries - 1:
                            time.sleep(2 * (attempt + 1))
                            
                if success:
                    break # Break key loop, we got a response!
            
            if not response:
                logger.error(f"All Gemini API Keys failed or exhausted. Last error: {last_error}")
                return translate_fallback()

            result_text = response.text.strip()
            
            # Parse result
            for line in result_text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Match format "1| text"
                parts = line.split('|', 1)
                if len(parts) == 2 and parts[0].strip().isdigit():
                    idx = int(parts[0].strip()) - 1
                    translated_dict[idx] = parts[1].strip()

            # Assemble segments
            translated_segments = []
            for i, seg in enumerate(segments):
                text_vi = translated_dict.get(i, "")
                if not text_vi:
                    # If Gemini missed a line, use fallback for that line
                    try:
                        text_vi = translator.translate(seg["text"]) if seg["text"].strip() else ""
                    except:
                        text_vi = seg["text"]

                translated_segments.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "text_zh": seg["text"],
                    "text_vi": text_vi,
                })
            
            return translated_segments, "Gemini AI"

        except Exception as e:
            logger.error(f"Gemini translation failed: {e}. Falling back to Google Translate.")
            return translate_fallback()

    await progress_cb("translate", 30, "AI đang dịch sang tiếng Việt...")
    translated, engine_name = await loop.run_in_executor(None, do_translate)

    if engine_name == "Gemini AI":
        await progress_cb("translate", 100, f"Đã dịch xong {len(translated)} đoạn (Thành công: Dùng {engine_name})")
    else:
        await progress_cb("translate", 100, f"Đã dịch xong {len(translated)} đoạn (Gemini bận, dùng {engine_name} dự phòng)")

    # Save translated segments
    with open(task_dir / "segments_vi.json", "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)

    return translated


# ============================================
# STEP 5: Text-to-Speech (TTS) - Multi-engine Vietnamese voiceover
# ============================================
async def _get_audio_duration(filepath: str) -> float:
    """Get audio duration in seconds using FFmpeg."""
    cmd = [FFMPEG_PATH, "-i", filepath, "-hide_banner"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    text = stderr.decode("utf-8", errors="ignore")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", text)
    if match:
        h, m, s, cs = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
        return h * 3600 + m * 60 + s + cs / 100.0
    return 0.0


async def _speed_up_audio(input_path: str, output_path: str, speed: float):
    """Speed up audio using FFmpeg atempo filter.
    atempo accepts 0.5-100.0, but for reliability we chain 2.0 filters.
    """
    # Build atempo chain: each atempo max 2.0
    filters = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    if remaining > 1.01:
        filters.append(f"atempo={remaining:.4f}")

    if not filters:
        return  # No speedup needed

    filter_str = ",".join(filters)
    cmd = [
        FFMPEG_PATH, "-i", input_path,
        "-af", filter_str,
        "-y", output_path
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await proc.wait()


# --- Individual TTS Engine Handlers ---

async def _tts_edge(text: str, voice_id: str, output_path: Path) -> bool:
    """Generate audio using Microsoft Edge-TTS."""
    import edge_tts
    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(text, voice_id)
            await communicate.save(str(output_path))
            if output_path.exists() and output_path.stat().st_size > 100:
                return True
        except Exception as e:
            logger.warning(f"Edge-TTS attempt {attempt+1} failed: {e}")
        await asyncio.sleep(1.5)
    return False


async def _tts_gtts(text: str, voice_id: str, output_path: Path) -> bool:
    """Generate audio using Google gTTS (nhấn nhá theo dấu câu)."""
    loop = asyncio.get_event_loop()

    def do_gtts():
        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang=voice_id or "vi", slow=False)
            tts.save(str(output_path))
            return output_path.exists() and output_path.stat().st_size > 100
        except Exception as e:
            logger.warning(f"gTTS error: {e}")
            return False

    return await loop.run_in_executor(None, do_gtts)


# Kokoro pipeline singleton (lazy init)
_kokoro_pipeline = None
_kokoro_lock = asyncio.Lock()


async def _get_kokoro_pipeline():
    """Get or create Kokoro Vietnamese pipeline (singleton)."""
    global _kokoro_pipeline
    if _kokoro_pipeline is not None:
        return _kokoro_pipeline

    async with _kokoro_lock:
        if _kokoro_pipeline is not None:
            return _kokoro_pipeline

        loop = asyncio.get_event_loop()

        def init_kokoro():
            try:
                from kokoro_vietnamese import KokoroVietnamese
                pipeline = KokoroVietnamese(device="cpu")
                return pipeline
            except Exception as e:
                logger.error(f"Failed to init Kokoro: {e}")
                return None

        _kokoro_pipeline = await loop.run_in_executor(None, init_kokoro)
        return _kokoro_pipeline


async def _tts_kokoro(text: str, voice_id: str, output_path: Path) -> bool:
    """Generate audio using Kokoro Vietnamese TTS."""
    loop = asyncio.get_event_loop()
    pipeline = await _get_kokoro_pipeline()

    if pipeline is None:
        logger.error("Kokoro pipeline not available")
        return False

    def do_kokoro():
        try:
            import soundfile as sf
            import torch
            from kokoro_vietnamese.core import resolve_voicepack_filename, _download_or_resolve, DEFAULT_HF_REPO_ID, DEFAULT_VOICEPACK_FILE
            
            # Dynamically load the correct voicepack for the requested voice_id
            voicepack_filename = resolve_voicepack_filename(voice_id, None)
            voicepack_path = _download_or_resolve(DEFAULT_HF_REPO_ID, DEFAULT_VOICEPACK_FILE, voicepack_filename)
            pipeline.voicepack = torch.load(voicepack_path, map_location='cpu', weights_only=True)

            # Generate audio
            audio, _ = pipeline.synthesize(text)

            if audio is None:
                return False

            # Save as WAV first, then convert to MP3 via FFmpeg
            wav_path = str(output_path).replace('.mp3', '_kokoro.wav')
            sf.write(wav_path, audio, 24000)

            return Path(wav_path).exists() and Path(wav_path).stat().st_size > 100
        except Exception as e:
            logger.error(f"Kokoro TTS error: {e}")
            return False

    result = await loop.run_in_executor(None, do_kokoro)

    if result:
        # Convert WAV to MP3
        wav_path = str(output_path).replace('.mp3', '_kokoro.wav')
        cmd = [
            FFMPEG_PATH, "-i", wav_path,
            "-acodec", "libmp3lame", "-ab", "128k",
            "-y", str(output_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.wait()

        # Clean up WAV
        try:
            Path(wav_path).unlink(missing_ok=True)
        except Exception:
            pass

        return output_path.exists() and output_path.stat().st_size > 100

    return False


# TTS engine dispatch map
TTS_HANDLERS = {
    "edge-tts": _tts_edge,
    "gtts": _tts_gtts,
    "kokoro": _tts_kokoro,
}


async def _generate_tts_segment(text: str, engine: str, voice_id: str,
                                 output_path: Path) -> bool:
    """Generate a single TTS segment using the specified engine.
    Falls back to Edge-TTS if the chosen engine fails.
    """
    handler = TTS_HANDLERS.get(engine)
    if handler:
        success = await handler(text, voice_id, output_path)
        if success:
            return True
        logger.warning(f"TTS engine '{engine}' failed, falling back to Edge-TTS")

    # Fallback to Edge-TTS
    return await _tts_edge(text, "vi-VN-HoaiMyNeural", output_path)


async def step_voiceover(task_dir: Path, segments: list, voice: str,
                          progress_cb: Callable) -> str:
    """Generate Vietnamese voiceover using the selected TTS engine with auto speed adjustment."""
    # Resolve voice config from tts_manager
    voice_config = get_voice_info(voice)
    engine = voice_config["engine"]
    voice_id = voice_config["voice_id"]
    engine_label = voice_config.get("engine_label", engine)

    await progress_cb("voiceover", 0, f"Đang chuẩn bị lồng tiếng ({engine_label})...")

    voiceover_dir = task_dir / "voice_parts"
    if voiceover_dir.exists():
        import shutil
        shutil.rmtree(voiceover_dir, ignore_errors=True)
    voiceover_dir.mkdir(exist_ok=True)

    # Check engine availability, fallback if needed
    if not check_engine_available(engine):
        logger.warning(f"Engine '{engine}' not available, falling back to Edge-TTS")
        engine = "edge-tts"
        voice_id = "vi-VN-HoaiMyNeural"
        engine_label = "Edge-TTS (dự phòng)"
        await progress_cb("voiceover", 0,
            f"{voice_config['engine_label']} chưa cài, dùng Edge-TTS dự phòng...")

    # Generate audio for each segment
    total = len(segments)
    audio_parts = []
    current_time = 0.0

    for i, seg in enumerate(segments):
        text = seg.get("text_vi", seg.get("text", ""))
        if not text.strip():
            continue

        part_file = voiceover_dir / f"part_{i:04d}.mp3"

        try:
            tts_ok = await _generate_tts_segment(text, engine, voice_id, part_file)

            if not tts_ok:
                logger.warning(f"TTS failed for segment {i}")
                continue

            # Small delay between segments for cloud engines
            if engine in ("edge-tts", "gtts") and i % 5 == 4:
                await asyncio.sleep(0.5)

            # Get actual audio duration
            audio_dur = await _get_audio_duration(str(part_file))

            # Strictly adhere to subtitle start time to prevent timeline drift
            seg_start = seg["start"]

            # Find the intended start of the NEXT segment to compute max_allowed
            next_start = None
            for j in range(i + 1, len(segments)):
                ns = segments[j].get("start", 0)
                if ns > seg_start:
                    next_start = ns
                    break

            if next_start is not None:
                max_allowed = next_start - seg_start
            else:
                max_allowed = seg["end"] - seg_start
                if max_allowed <= 0: max_allowed = 2.0

            # Leave small buffer
            max_allowed = max(max_allowed - 0.05, 0.2)

            # Uniform speedup + Dynamic cap
            base_speed = 1.15
            
            if audio_dur > 0:
                needed_speed = audio_dur / max_allowed if max_allowed > 0.1 else base_speed
                # Apply base speed, but cap at 1.8x maximum to prevent chipmunk voice while ensuring sync
                final_speed = max(base_speed, needed_speed)
                final_speed = min(final_speed, 1.8)

                if final_speed > 1.02: # Only speed up if noticeably faster
                    sped_file = voiceover_dir / f"part_{i:04d}_fast.mp3"
                    await _speed_up_audio(str(part_file), str(sped_file), final_speed)
                    if sped_file.exists() and sped_file.stat().st_size > 100:
                        part_file = sped_file
                        audio_dur = await _get_audio_duration(str(part_file))

            # Update current_time for the next segment
            current_time = seg_start + audio_dur

            audio_parts.append({
                "file": str(part_file),
                "start": seg_start,
                "end": current_time,
            })
        except Exception as e:
            logger.warning(f"TTS error for segment {i}: {e}")

        pct = int(20 + (i / max(total, 1)) * 70)
        await progress_cb("voiceover", pct, f"[{engine_label}] Đoạn {i+1}/{total}...")

    # Merge all voice parts with correct timing using FFmpeg
    voiceover_path = task_dir / "voiceover.mp3"

    if audio_parts:
        await _merge_voice_parts(task_dir, audio_parts, voiceover_path)

    await progress_cb("voiceover", 100, f"Đã lồng tiếng thành công ({engine_label})!")
    return str(voiceover_path)


async def _merge_voice_parts(task_dir: Path, parts: list, output: Path):
    """Merge voice parts with timing into a single audio track.
    Uses batched approach to avoid Windows command line length limits.
    """
    if not parts:
        return

    # Get total video duration from original
    original = task_dir / "original.mp4"
    probe_cmd = [
        FFMPEG_PATH, "-i", str(original), "-hide_banner"
    ]
    proc = await asyncio.create_subprocess_exec(
        *probe_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    stderr_text = stderr.decode("utf-8", errors="ignore")

    total_duration = 30  # default
    dur_match = re.search(r"Duration: (\d+):(\d+):(\d+)", stderr_text)
    if dur_match:
        h, m, s = int(dur_match.group(1)), int(dur_match.group(2)), int(dur_match.group(3))
        total_duration = h * 3600 + m * 60 + s + 1

    # For small number of parts, use direct approach
    BATCH_SIZE = 40

    if len(parts) <= BATCH_SIZE:
        await _merge_parts_direct(parts, total_duration, output)
        return

    # For many parts: batch merge
    batch_dir = task_dir / "voice_batches"
    if batch_dir.exists():
        import shutil
        shutil.rmtree(batch_dir, ignore_errors=True)
    batch_dir.mkdir(exist_ok=True)

    batch_outputs = []
    for batch_idx in range(0, len(parts), BATCH_SIZE):
        batch = parts[batch_idx:batch_idx + BATCH_SIZE]
        batch_out = batch_dir / f"batch_{batch_idx:04d}.mp3"
        await _merge_parts_direct(batch, total_duration, batch_out)
        if batch_out.exists() and batch_out.stat().st_size > 100:
            batch_outputs.append(str(batch_out))

    if not batch_outputs:
        return

    if len(batch_outputs) == 1:
        import shutil
        shutil.copy2(batch_outputs[0], output)
        return

    # Final merge: mix all batch outputs together
    cmd = [FFMPEG_PATH]
    for bo in batch_outputs:
        cmd.extend(["-i", bo])

    mix_inputs = "".join(f"[{i}:a]" for i in range(len(batch_outputs)))
    filter_str = f"{mix_inputs}amix=inputs={len(batch_outputs)}:duration=longest:normalize=0[out]"

    cmd.extend([
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-y", str(output)
    ])

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await proc.wait()


async def _merge_parts_direct(parts: list, total_duration: int, output: Path):
    """Merge a small batch of voice parts into one audio track."""
    inputs = []
    filter_parts = []

    # Silent base track
    filter_parts.append(
        f"anullsrc=r=44100:cl=mono:d={total_duration}[silence]"
    )

    for i, part in enumerate(parts):
        inputs.extend(["-i", part["file"]])
        delay_ms = int(part["start"] * 1000)
        filter_parts.append(
            f"[{i}:a]adelay={delay_ms}|{delay_ms},aresample=44100[d{i}]"
        )

    # Mix all together
    mix_inputs = "[silence]" + "".join(f"[d{i}]" for i in range(len(parts)))
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(parts)+1}:duration=first:dropout_transition=0:normalize=0[out]"
    )

    filter_complex = ";".join(filter_parts)

    cmd = [FFMPEG_PATH]
    cmd.extend(inputs)
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-y", str(output)
    ])

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await proc.wait()


# ============================================
# STEP: Blur hardcoded Chinese text in video
# ============================================
async def _get_video_dimensions(video_path: Path) -> tuple:
    """Get video width and height using FFmpeg probe."""
    cmd = [FFMPEG_PATH, "-i", str(video_path), "-hide_banner"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    stderr_text = stderr.decode("utf-8", errors="ignore")

    width, height = 1080, 1920  # Default for Douyin vertical videos
    match = re.search(r"(\d{3,4})x(\d{3,4})", stderr_text)
    if match:
        width, height = int(match.group(1)), int(match.group(2))
    return width, height


async def step_blur_chinese_text(task_dir: Path, segments: list,
                                  progress_cb: Callable) -> dict:
    """Detect and blur hardcoded Chinese text, return text region info."""
    await progress_cb("blur_chinese", 0, "Đang phát hiện vùng chữ Trung trong video...")

    clean = task_dir / "clean.mp4"
    if not clean.exists():
        clean = task_dir / "original.mp4"

    blurred = task_dir / "blurred.mp4"
    frames_dir = task_dir / "ocr_frames"
    frames_dir.mkdir(exist_ok=True)

    # Get video dimensions
    width, height = await _get_video_dimensions(clean)

    await progress_cb("blur_chinese", 10, "Đang trích xuất frame mẫu...")

    # Sample frames at subtitle timestamps
    sample_times = []
    for seg in segments:
        mid = (seg.get("start", 0) + seg.get("end", 0)) / 2
        sample_times.append(round(mid, 2))

    # Limit to 8 sample frames for speed
    if len(sample_times) > 8:
        step_size = len(sample_times) / 8
        sample_times = [sample_times[int(i * step_size)] for i in range(8)]

    # Extract frames using FFmpeg
    for i, t in enumerate(sample_times):
        frame_path = frames_dir / f"frame_{i:03d}.png"
        cmd = [
            FFMPEG_PATH, "-ss", str(t), "-i", str(clean),
            "-frames:v", "1", "-q:v", "2", "-y", str(frame_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.wait()

    await progress_cb("blur_chinese", 30, "Đang nhận diện chữ Trung bằng AI OCR...")

    # Use easyocr to detect Chinese text
    loop = asyncio.get_event_loop()

    def do_ocr():
        try:
            import easyocr
            reader = easyocr.Reader(['ch_sim', 'ch_tra'], gpu=False, verbose=False)
        except ImportError:
            logger.error("easyocr not installed. pip install easyocr")
            return []

        all_boxes = []
        for frame_file in sorted(frames_dir.glob("frame_*.png")):
            try:
                results = reader.readtext(str(frame_file))
                for (bbox, text, conf) in results:
                    if conf > 0.25 and len(text.strip()) > 0:
                        # bbox: [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
                        all_boxes.append({
                            "x1": int(bbox[0][0]),
                            "y1": int(bbox[0][1]),
                            "x2": int(bbox[2][0]),
                            "y2": int(bbox[2][1]),
                            "text": text,
                            "conf": conf
                        })
            except Exception as e:
                logger.warning(f"OCR error for {frame_file.name}: {e}")

        return all_boxes

    all_boxes = await loop.run_in_executor(None, do_ocr)

    await progress_cb("blur_chinese", 60, "Đang tính vùng chữ Trung cần làm mờ...")

    if not all_boxes:
        # Fallback: assume bottom 12% of video is subtitle area
        logger.warning("No Chinese text detected by OCR, using fallback region")
        region_x = int(width * 0.05)
        region_y = int(height * 0.82)
        region_w = int(width * 0.9)
        region_h = int(height * 0.12)
        # Ensure even dimensions
        region_w = region_w // 2 * 2
        region_h = region_h // 2 * 2
        text_region = {
            "x": region_x, "y": region_y,
            "w": region_w, "h": region_h,
            "video_width": width, "video_height": height,
            "margin_v": max(10, height - region_y - region_h),
            "detected": False
        }
    else:
        # Focus on subtitle area (bottom 50% of video)
        subtitle_boxes = [b for b in all_boxes if b["y1"] > height * 0.5]
        if not subtitle_boxes:
            subtitle_boxes = all_boxes

        padding = 20
        min_x = max(0, min(b["x1"] for b in subtitle_boxes) - padding)
        min_y = max(0, min(b["y1"] for b in subtitle_boxes) - padding)
        max_x = min(width, max(b["x2"] for b in subtitle_boxes) + padding)
        max_y = min(height, max(b["y2"] for b in subtitle_boxes) + padding)

        # Ensure even dimensions for FFmpeg
        blur_w = ((max_x - min_x) // 2) * 2
        blur_h = ((max_y - min_y) // 2) * 2

        # Ensure minimum size
        blur_w = max(blur_w, 100)
        blur_h = max(blur_h, 40)

        text_region = {
            "x": min_x, "y": min_y,
            "w": blur_w, "h": blur_h,
            "video_width": width, "video_height": height,
            "margin_v": max(10, height - max_y),
            "detected": True,
            "num_detections": len(subtitle_boxes)
        }

    # Save text region info for render step
    with open(task_dir / "text_region.json", "w", encoding="utf-8") as f:
        json.dump(text_region, f, indent=2)

    logger.info(f"Blur region: x={text_region['x']}, y={text_region['y']}, "
                f"w={text_region['w']}, h={text_region['h']}, "
                f"detected={text_region.get('detected')}")

    await progress_cb("blur_chinese", 70, "Đang làm mờ vùng chữ Trung trong video...")

    # Build FFmpeg blur filter
    x, y, w, h = text_region["x"], text_region["y"], text_region["w"], text_region["h"]

    # Time-based enable: only blur during subtitle timestamps
    enable_parts = []
    for seg in segments:
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        if end > start:
            enable_parts.append(f"between(t\\,{start:.2f}\\,{end:.2f})")

    if enable_parts and len(enable_parts) <= 50:
        enable_expr = "+".join(enable_parts)
        vf = (
            f"split=2[main][forblur];"
            f"[forblur]crop={w}:{h}:{x}:{y},boxblur=20:5[blurred_region];"
            f"[main][blurred_region]overlay={x}:{y}:enable='{enable_expr}'"
        )
    else:
        # Full video blur for too many segments
        vf = (
            f"split=2[main][forblur];"
            f"[forblur]crop={w}:{h}:{x}:{y},boxblur=20:5[blurred_region];"
            f"[main][blurred_region]overlay={x}:{y}"
        )

    cmd = [
        FFMPEG_PATH, "-i", str(clean),
        "-filter_complex", vf,
        "-c:a", "copy",
        "-y", str(blurred)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"Blur FFmpeg error: {stderr.decode('utf-8', errors='ignore')[:500]}")
        # Fallback: copy clean as blurred
        import shutil
        shutil.copy2(clean, blurred)

    if not blurred.exists() or blurred.stat().st_size < 1000:
        import shutil
        shutil.copy2(clean, blurred)

    await progress_cb("blur_chinese", 100, "Đã làm mờ chữ Trung thành công!")

    return text_region


# ============================================
# STEP 6: Create subtitles & Render final video
# ============================================
async def step_render(task_dir: Path, segments: list, options: dict,
                       progress_cb: Callable) -> str:
    """Create SRT subtitles and render final video."""
    await progress_cb("render", 0, "Đang tạo phụ đề tiếng Việt...")

    clean_video = task_dir / "clean.mp4"
    if not clean_video.exists():
        clean_video = task_dir / "original.mp4"
    source_video = clean_video

    voiceover = task_dir / "voiceover.mp3"
    subtitle_path = task_dir / "subtitle.ass"
    
    # Check for extracted BGM
    bgm_path = None
    if options.get("keep_bgm", False):
        possible_bgm_mp3 = task_dir / "demucs_out" / "htdemucs" / "no_vocals.mp3"
        possible_bgm_wav = task_dir / "demucs_out" / "htdemucs" / "no_vocals.wav"
        if possible_bgm_mp3.exists():
            bgm_path = possible_bgm_mp3
        elif possible_bgm_wav.exists():
            bgm_path = possible_bgm_wav
    
    output_path = task_dir / "output.mp4"
    if output_path.exists():
        try:
            output_path.unlink()
        except Exception:
            # Windows file lock fallback
            import time
            output_path = task_dir / f"output_{int(time.time())}.mp4"

    # Determine subtitle style
    sub_style = SUBTITLE_STYLE
    if "margin_v" in options:
        margin_v = options["margin_v"]
        sub_style = re.sub(r"MarginV=-?\d+", f"MarginV={margin_v}", sub_style)

    # Generate ASS file
    has_subtitle = options.get("subtitle", True) and segments
    if has_subtitle:
        video_w, video_h = await _get_video_dimensions(source_video)
        _generate_ass(segments, subtitle_path, sub_style, video_w, video_h, options)
        await progress_cb("render", 20, "Đã tạo file phụ đề ASS!")

    has_voiceover = options.get("voiceover", True) and voiceover.exists()
    has_subtitle = has_subtitle and subtitle_path.exists()

    await progress_cb("render", 30, "Đang render video cuối cùng...")

    # Build the FFmpeg command properly
    cmd = _build_final_render_cmd(
        source_video, 
        voiceover if has_voiceover else None,
        bgm_path,
        subtitle_path if has_subtitle else None, 
        output_path,
        sub_style
    )

    await progress_cb("render", 50, "Đang encode video (có thể mất 1-2 phút)...")

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"FFmpeg render error: {stderr.decode('utf-8', errors='ignore')[:500]}")
        # Fallback: simpler render without subtitle
        await _simple_render(source_video, voiceover, output_path, options)

    await progress_cb("render", 100, "Đã render xong video!")
    return str(output_path)


def _build_final_render_cmd(clean_video, voiceover, bgm_path, subtitle_path, output_path,
                             subtitle_style=None, bgm_volume=0.6):
    """Build FFmpeg command handling subtitle + voiceover + bgm without conflicts."""
    if subtitle_style is None:
        subtitle_style = SUBTITLE_STYLE

    cmd = [FFMPEG_PATH, "-i", str(clean_video)]

    if voiceover:
        cmd.extend(["-i", str(voiceover)])
    if bgm_path:
        cmd.extend(["-i", str(bgm_path)])

    filter_complex = []
    
    # Video filter for subtitles
    if subtitle_path:
        sub_escaped = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
        filter_complex.append(f"[0:v]subtitles='{sub_escaped}'[v]")
    
    # Audio filter
    if voiceover and bgm_path:
        # Mix bgm and voiceover.
        filter_complex.append(f"[2:a]volume={bgm_volume}[bgm];[1:a][bgm]amix=inputs=2:duration=longest[a]")
    elif voiceover:
        filter_complex.append("[1:a]anull[a]")
    elif bgm_path:
        filter_complex.append(f"[1:a]volume={bgm_volume}[a]")

    if filter_complex:
        cmd.extend(["-filter_complex", ";".join(filter_complex)])
        
        # Map video
        if subtitle_path:
            cmd.extend(["-map", "[v]"])
        else:
            cmd.extend(["-map", "0:v"])
            
        # Map audio
        if voiceover or bgm_path:
            cmd.extend(["-map", "[a]"])
        else:
            cmd.extend(["-map", "0:a"])
    else:
        # Fallback if neither voiceover nor bgm is used
        cmd.extend(["-map", "0:v", "-map", "0:a"])

    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-y", str(output_path),
    ])
    return cmd


async def _simple_render(clean_video, voiceover, output_path, options):
    """Simple fallback render without subtitle burn-in."""
    cmd = [FFMPEG_PATH, "-i", str(clean_video)]

    has_voiceover = options.get("voiceover", True) and voiceover.exists()
    if has_voiceover:
        cmd.extend(["-i", str(voiceover)])
        cmd.extend([
            "-map", "0:v", "-map", "1:a",
        ])
    else:
        cmd.extend(["-map", "0:v", "-map", "0:a"])

    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-y", str(output_path),
    ])

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await proc.wait()


def _generate_ass(segments: list, output_path: Path, style_str: str, video_w: int = 1080, video_h: int = 1920, options: dict = None):
    """Generate ASS subtitle file from translated segments."""
    options = options or {}
    
    # Calculate responsive font size (approx 6.9% of height to match old 133/1920 ratio)
    font_size = int(video_h * 0.069)
    
    # Support new pos_x and pos_y percentages from drag-and-drop UI
    use_pos = False
    pos_x_px = 0
    pos_y_px = 0
    
    if "pos_x" in options and "pos_y" in options:
        use_pos = True
        pos_x_px = int((options["pos_x"] / 100.0) * video_w)
        pos_y_px = int((options["pos_y"] / 100.0) * video_h)

    # Extract MarginV if present (legacy support)
    margin_v = 25
    import re
    match = re.search(r"MarginV=(-?\d+)", style_str)
    if match:
        margin_v = int(match.group(1))

    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_w}
PlayResY: {video_h}
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,15,0,2,20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def format_ass_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100) # ASS uses centiseconds
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        for i, seg in enumerate(segments):
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            text = seg.get("text_vi", seg.get("text", ""))

            # Extend end time
            if i < len(segments) - 1:
                next_start = segments[i+1].get("start", 0)
                gap = next_start - end
                if gap > 0:
                    if gap < 2.0:
                        end = next_start - 0.001
                    else:
                        end += 1.5
            else:
                end += 1.5

            start_str = format_ass_time(start)
            end_str = format_ass_time(end)
            
            # Replace newlines with ASS newline tag \N
            text = text.replace('\n', '\\N')
            
            # Apply absolute positioning if using drag-and-drop
            if use_pos:
                text = f"{{\\pos({pos_x_px},{pos_y_px})}}{text}"

            f.write(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}\n")


async def step_extract_bgm(task_dir: Path, progress_cb: Callable) -> Path:
    """Extract background music/audio using Demucs."""
    await progress_cb("extract_bgm", 0, "Đang khởi tạo công cụ tách nhạc (Demucs)...")
    
    clean_video = task_dir / "clean.mp4"
    if not clean_video.exists():
        clean_video = task_dir / "original.mp4"
        
    out_dir = task_dir / "demucs_out"
    out_dir.mkdir(exist_ok=True)
    
    cmd = [
        "python", "-m", "demucs.separate",
        "--two-stems", "vocals",
        "-n", "htdemucs",
        "--mp3",
        "--filename", "{stem}.{ext}",
        "-o", str(out_dir),
        str(clean_video)
    ]
    
    await progress_cb("extract_bgm", 10, "Đang tách nhạc nền gốc (có thể mất vài phút)...")
    
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        logger.error(f"Demucs error: {stderr.decode('utf-8', errors='ignore')}")
        raise Exception("Lỗi khi tách nhạc nền video.")
        
    no_vocals_path = out_dir / "htdemucs" / "no_vocals.mp3"
    
    if not no_vocals_path.exists():
        logger.error(f"Expected Demucs output not found at: {no_vocals_path}")
        raise Exception("Không tìm thấy file nhạc nền sau khi tách.")
        
    return no_vocals_path


# ============================================
# MAIN PIPELINE ORCHESTRATOR
# ============================================
async def run_pipeline(task_id: str, url: str, options: dict,
                        progress_callback: Callable) -> dict:
    """
    Run the complete video processing pipeline.
    
    Args:
        task_id: Unique task identifier
        url: Douyin video URL
        options: Processing options dict:
            - translate: bool
            - subtitle: bool
            - voiceover: bool
            - watermark: bool
            - blur_chinese: bool
            - voice: 'male' | 'female'
        progress_callback: async function(step, percent, message)
    
    Returns:
        dict with result info
    """
    task_dir = TEMP_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    result = {"task_id": task_id, "status": "processing"}

    try:
        # Step 1: Download
        info = await step_download(task_dir, url, progress_callback)
        result["video_info"] = info

        # Step 2: Remove watermark (if selected)
        if options.get("watermark", True):
            await step_remove_watermark(task_dir, progress_callback)
        else:
            # Copy original as clean
            import shutil
            original = task_dir / "original.mp4"
            clean = task_dir / "clean.mp4"
            if original.exists():
                shutil.copy2(original, clean)

        # Step 3: Transcribe (if translate or subtitle or blur_chinese selected)
        segments = []
        if options.get("translate", True) or options.get("subtitle", True) or options.get("blur_chinese"):
            segments = await step_transcribe(task_dir, progress_callback)

        # Step 4: Translate (if selected or blur_chinese needs Vietnamese text)
        translated_segments = segments
        if (options.get("translate", True) or options.get("blur_chinese")) and segments:
            translated_segments = await step_translate(
                task_dir, segments, options, progress_callback
            )

        # Step 5: Blur Chinese text → now handled by subtitle style in render step
        logger.info(f"[DEBUG] run_pipeline blur_chinese={options.get('blur_chinese')}, "
                     f"has_segments={bool(translated_segments)}, "
                     f"all_options={options}")

        # Step 6: Voiceover (if selected)
        if options.get("voiceover", True) and translated_segments:
            voice = options.get("voice", "female")
            await step_voiceover(
                task_dir, translated_segments, voice, progress_callback
            )

        # Step 6.5: Extract BGM (if selected)
        if options.get("keep_bgm", False):
            try:
                await step_extract_bgm(task_dir, progress_callback)
            except Exception as e:
                logger.error(f"Failed to extract BGM: {e}")
                # Continue without BGM if extraction fails

        # Step 7: Render final video
        await step_render(task_dir, translated_segments, options, progress_callback)

        # Get output file info
        output = task_dir / "output.mp4"
        if output.exists():
            result["status"] = "completed"
            result["output_path"] = str(output)
            result["file_size"] = output.stat().st_size
            result["file_size_mb"] = round(output.stat().st_size / (1024 * 1024), 1)
        else:
            result["status"] = "error"
            result["error"] = "Output file not found"

    except Exception as e:
        logger.exception(f"Pipeline error for task {task_id}")
        result["status"] = "error"
        result["error"] = str(e)
        await progress_callback("error", 0, f"Lỗi: {str(e)}")

    return result


def get_video_info(url: str) -> dict:
    """Extract video info using Playwright without downloading."""
    url = normalize_douyin_url(url)
    
    info = get_douyin_metadata_playwright(url)

    duration = info.get("duration", 0)
    minutes = int(duration // 60)
    seconds = int(duration % 60)

    return {
        "title": info.get("title", "Video Douyin"),
        "duration": duration,
        "duration_text": f"{minutes} phút {seconds} giây" if minutes else f"{seconds} giây",
        "duration_short": f"{minutes}:{seconds:02d}" if minutes else f"0:{seconds:02d}",
        "thumbnail": info.get("thumbnail", ""),
        "view_count": info.get("view_count", 0),
        "like_count": info.get("like_count", 0),
        "uploader": info.get("uploader", ""),
        "description": info.get("title", ""),
    }


