"""
TTS Engine Manager
Quản lý các engine TTS: kiểm tra availability, download models, registry giọng nói.
Hỗ trợ: Edge-TTS, gTTS (Google), Kokoro Vietnamese
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent / "models"

# ============================================
# TTS ENGINE REGISTRY
# ============================================
TTS_VOICES = {
    # --- Edge-TTS (Microsoft) ---
    "edge_female": {
        "engine": "edge-tts",
        "voice_id": "vi-VN-HoaiMyNeural",
        "label": "HoàiMy (Nữ)",
        "engine_label": "Microsoft Edge",
        "gender": "female",
        "type": "cloud",
        "description": "Giọng nữ nhẹ nhàng, dễ nghe",
        "icon": "microsoft",
    },
    "edge_male": {
        "engine": "edge-tts",
        "voice_id": "vi-VN-NamMinhNeural",
        "label": "NamMinh (Nam)",
        "engine_label": "Microsoft Edge",
        "gender": "male",
        "type": "cloud",
        "description": "Giọng nam trầm ấm, chuyên nghiệp",
        "icon": "microsoft",
    },
    # --- gTTS (Google) ---
    "gtts_vi": {
        "engine": "gtts",
        "voice_id": "vi",
        "label": "Google Vietnamese",
        "engine_label": "Google TTS",
        "gender": "female",
        "type": "cloud",
        "description": "Nhấn nhá theo dấu câu, đa ngôn ngữ",
        "icon": "google",
    },
    # --- Kokoro Vietnamese ---
    "kokoro_diem_trinh": {
        "engine": "kokoro",
        "voice_id": "diem_trinh",
        "label": "Diễm Trinh",
        "engine_label": "Kokoro AI",
        "gender": "female",
        "type": "local",
        "description": "Giọng nữ trẻ trung",
        "icon": "kokoro",
    },
    "kokoro_mai_linh": {
        "engine": "kokoro",
        "voice_id": "mai_linh",
        "label": "Mai Linh",
        "engine_label": "Kokoro AI",
        "gender": "female",
        "type": "local",
        "description": "Giọng nữ nhẹ nhàng",
        "icon": "kokoro",
    },
    "kokoro_mai_loan": {
        "engine": "kokoro",
        "voice_id": "mai_loan",
        "label": "Mai Loan",
        "engine_label": "Kokoro AI",
        "gender": "female",
        "type": "local",
        "description": "Giọng nữ truyền cảm",
        "icon": "kokoro",
    },
    "kokoro_my_yen": {
        "engine": "kokoro",
        "voice_id": "my_yen",
        "label": "Mỹ Yến",
        "engine_label": "Kokoro AI",
        "gender": "female",
        "type": "local",
        "description": "Giọng nữ ấm áp",
        "icon": "kokoro",
    },
    "kokoro_ngoc_huyen": {
        "engine": "kokoro",
        "voice_id": "ngoc_huyen",
        "label": "Ngọc Huyền",
        "engine_label": "Kokoro AI",
        "gender": "female",
        "type": "local",
        "description": "Giọng nữ trong trẻo",
        "icon": "kokoro",
    },
    "kokoro_thuc_trinh": {
        "engine": "kokoro",
        "voice_id": "thuc_trinh",
        "label": "Thục Trinh",
        "engine_label": "Kokoro AI",
        "gender": "female",
        "type": "local",
        "description": "Giọng nữ dịu dàng",
        "icon": "kokoro",
    },
    "kokoro_hung_thinh": {
        "engine": "kokoro",
        "voice_id": "hung_thinh",
        "label": "Hưng Thịnh",
        "engine_label": "Kokoro AI",
        "gender": "male",
        "type": "local",
        "description": "Giọng nam mạnh mẽ",
        "icon": "kokoro",
    },
    "kokoro_manh_dung": {
        "engine": "kokoro",
        "voice_id": "manh_dung",
        "label": "Mạnh Dũng",
        "engine_label": "Kokoro AI",
        "gender": "male",
        "type": "local",
        "description": "Giọng nam trầm ấm",
        "icon": "kokoro",
    },
    "kokoro_phat_tai": {
        "engine": "kokoro",
        "voice_id": "phat_tai",
        "label": "Phát Tài",
        "engine_label": "Kokoro AI",
        "gender": "male",
        "type": "local",
        "description": "Giọng nam trẻ trung",
        "icon": "kokoro",
    },
    "kokoro_thanh_dat": {
        "engine": "kokoro",
        "voice_id": "thanh_dat",
        "label": "Thành Đạt",
        "engine_label": "Kokoro AI",
        "gender": "male",
        "type": "local",
        "description": "Giọng nam chuyên nghiệp",
        "icon": "kokoro",
    },
    "kokoro_tuan_ngoc": {
        "engine": "kokoro",
        "voice_id": "tuan_ngoc",
        "label": "Tuấn Ngọc",
        "engine_label": "Kokoro AI",
        "gender": "male",
        "type": "local",
        "description": "Giọng nam phong cách",
        "icon": "kokoro",
    },
    "kokoro_duc_an": {
        "engine": "kokoro",
        "voice_id": "duc_an",
        "label": "Đức An",
        "engine_label": "Kokoro AI",
        "gender": "male",
        "type": "local",
        "description": "Giọng nam điềm đạm",
        "icon": "kokoro",
    },
    "kokoro_duc_duy": {
        "engine": "kokoro",
        "voice_id": "duc_duy",
        "label": "Đức Duy",
        "engine_label": "Kokoro AI",
        "gender": "male",
        "type": "local",
        "description": "Giọng nam rõ ràng",
        "icon": "kokoro",
    },
    "kokoro_storyvert": {
        "engine": "kokoro",
        "voice_id": "storyvert",
        "label": "Storyvert",
        "engine_label": "Kokoro AI",
        "gender": "neutral",
        "type": "local",
        "description": "Giọng kể chuyện truyền cảm",
        "icon": "kokoro",
    },
}

# ============================================
# ENGINE AVAILABILITY CHECK
# ============================================
_engine_cache = {}


def check_engine_available(engine_name: str) -> bool:
    """Check if a TTS engine package is installed and ready."""
    if engine_name in _engine_cache:
        return _engine_cache[engine_name]

    available = False
    try:
        if engine_name == "edge-tts":
            import edge_tts
            available = True
        elif engine_name == "gtts":
            from gtts import gTTS
            available = True
        elif engine_name == "kokoro":
            available = _check_kokoro_available()
    except ImportError:
        available = False
    except Exception as e:
        logger.warning(f"Error checking engine {engine_name}: {e}")
        available = False

    _engine_cache[engine_name] = available
    return available


def _check_kokoro_available() -> bool:
    """Check if Kokoro Vietnamese is installed and ready."""
    try:
        # Check if the kokoro-vietnamese package or model is available
        from kokoro_vietnamese import KokoroVietnamese
        return True
    except ImportError:
        pass

    return False


def get_available_engines() -> dict:
    """Get list of all voices grouped by engine with availability status."""
    engines = {}

    for voice_key, voice_info in TTS_VOICES.items():
        engine = voice_info["engine"]
        if engine not in engines:
            engines[engine] = {
                "engine": engine,
                "label": voice_info["engine_label"],
                "type": voice_info["type"],
                "icon": voice_info["icon"],
                "available": check_engine_available(engine),
                "voices": [],
            }

        engines[engine]["voices"].append({
            "key": voice_key,
            "label": voice_info["label"],
            "gender": voice_info["gender"],
            "description": voice_info["description"],
        })

    return engines


def get_voice_info(voice_key: str) -> dict:
    """Get voice config by key. Falls back to edge_female if not found."""
    if voice_key in TTS_VOICES:
        return TTS_VOICES[voice_key]

    # Legacy compatibility: "male" -> "edge_male", "female" -> "edge_female"
    legacy_map = {
        "male": "edge_male",
        "female": "edge_female",
    }
    mapped = legacy_map.get(voice_key, "edge_female")
    return TTS_VOICES.get(mapped, TTS_VOICES["edge_female"])


def get_install_instructions(engine_name: str) -> str:
    """Get pip install command for an engine."""
    instructions = {
        "edge-tts": "pip install edge-tts",
        "gtts": "pip install gTTS",
        "kokoro": "pip install kokoro soundfile torch espeak-ng",
    }
    return instructions.get(engine_name, "")
