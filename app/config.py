import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # API Configuration
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_api_key_2: str = Field(default="", validation_alias="GEMINI_API_KEY_2")
    gemini_api_key_3: str = Field(default="", validation_alias="GEMINI_API_KEY_3")
    gemini_api_key_4: str = Field(default="", validation_alias="GEMINI_API_KEY_4")
    gemini_api_key_5: str = Field(default="", validation_alias="GEMINI_API_KEY_5")
    gemini_api_key_6: str = Field(default="", validation_alias="GEMINI_API_KEY_6")
    gemini_api_key_7: str = Field(default="", validation_alias="GEMINI_API_KEY_7")
    gemini_api_key_8: str = Field(default="", validation_alias="GEMINI_API_KEY_8")
    gemini_api_key_9: str = Field(default="", validation_alias="GEMINI_API_KEY_9")
    gemini_api_key_10: str = Field(default="", validation_alias="GEMINI_API_KEY_10")
    
    # Path Configuration
    default_output_folder: str = "./examples/outputs"
    default_music_folder: str = "./examples/music"
    default_source_folder: str = ""
    default_export_path: str = Field(default="", validation_alias="DEFAULT_EXPORT_PATH")
    
    # Render & Pipeline Configuration
    default_voice: str = "vi-VN-HoaiMyNeural" # edge-tts voice ID
    default_rate: str = "+0%"
    default_pitch: str = "+0Hz"
    default_target_language: str = "vi-VN"
    default_translation_mode: str = "natural"
    cleanup_intermediate_files: bool = True
    keep_debug_on_success: bool = False
    keep_temp_on_failure: bool = True
    
    # Channel Configuration
    channel_name: str = Field(default="AutoTool Review", validation_alias="CHANNEL_NAME")
    
    # Audio ducking default volumes
    original_volume: float = 0.25
    tts_volume: float = 1.0
    bgm_volume: float = 0.4

    # Subtitle cover / OCR detection defaults
    subtitle_cover_mode: str = "auto_detect_old_text"
    subtitle_bg_opacity: float = 0.20
    subtitle_mask_padding_x: int = 20
    subtitle_mask_padding_y: int = 12
    ocr_sample_interval_sec: float = 0.75
    ocr_crop_bottom_ratio: float = 0.45
    max_concurrent_jobs: int = Field(default=3, validation_alias="MAX_CONCURRENT_JOBS")
    whisper_model_size: str = Field(default="base", validation_alias="WHISPER_MODEL_SIZE")
    
    # App root folder
    auto_tool_root: Path = Path(__file__).resolve().parent.parent

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Global list of available TTS voices
AVAILABLE_VOICES = [
    # Vietnamese
    {"id": "vi-VN-HoaiMyNeural", "name": "Tiếng Việt - Nữ Nam (Hoài Mỹ)"},
    {"id": "vi-VN-NamMinhNeural", "name": "Tiếng Việt - Nam Trung (Nam Minh)"},
    # English
    {"id": "en-US-EmmaNeural", "name": "English US - Nữ (Emma)"},
    {"id": "en-US-BrianNeural", "name": "English US - Nam (Brian)"},
    # Spanish
    {"id": "es-MX-DaliaNeural", "name": "Español MX - Nữ (Dalia)"},
    {"id": "es-MX-JorgeNeural", "name": "Español MX - Nam (Jorge)"},
    {"id": "es-ES-ElviraNeural", "name": "Español ES - Nữ (Elvira)"},
    {"id": "es-ES-AlvaroNeural", "name": "Español ES - Nam (Alvaro)"},
    # Portuguese
    {"id": "pt-BR-FranciscaNeural", "name": "Português BR - Nữ (Francisca)"},
    {"id": "pt-BR-AntonioNeural", "name": "Português BR - Nam (Antonio)"},
    {"id": "pt-PT-RaquelNeural", "name": "Português PT - Nữ (Raquel)"},
    {"id": "pt-PT-DuarteNeural", "name": "Português PT - Nam (Duarte)"},
    # Russian
    {"id": "ru-RU-SvetlanaNeural", "name": "Русский - Nữ (Svetlana)"},
    {"id": "ru-RU-DmitryNeural", "name": "Русский - Nam (Dmitry)"},
    # Thai
    {"id": "th-TH-AcharaNeural", "name": "Thai - Nữ (Achara)"},
    {"id": "th-TH-NiwatNeural", "name": "Thai - Nam (Niwat)"},
    # Indonesian
    {"id": "id-ID-GadisNeural", "name": "Indonesian - Nữ (Gadis)"},
    {"id": "id-ID-ArdiNeural", "name": "Indonesian - Nam (Ardi)"},
    # Japanese
    {"id": "ja-JP-NanamiNeural", "name": "Japanese - Nữ (Nanami)"},
    {"id": "ja-JP-KeitaNeural", "name": "Japanese - Nam (Keita)"},
    # Korean
    {"id": "ko-KR-SunHiNeural", "name": "Korean - Nữ (SunHi)"},
    {"id": "ko-KR-InJoonNeural", "name": "Korean - Nam (InJoon)"},
]

# Global list of available translation tones
AVAILABLE_TONES = [
    {"id": "review_phim", "name": "Review Phim"},
    {"id": "funny", "name": "Hài Hước"},
    {"id": "dramatic", "name": "Kịch Tính"},
    {"id": "serious", "name": "Nghiêm Túc"},
    {"id": "sad", "name": "Buồn"},
    {"id": "energetic", "name": "Năng Động"},
]

# Global list of available TTS rates
AVAILABLE_RATES = [
    {"id": "-20%", "name": "Chậm (-20%)"},
    {"id": "-10%", "name": "Chậm vừa (-10%)"},
    {"id": "-5%", "name": "Chậm nhẹ (-5%)"},
    {"id": "+0%", "name": "Mặc định (+0%)"},
    {"id": "+5%", "name": "Nhanh nhẹ (+5%)"},
    {"id": "+10%", "name": "Nhanh (+10%)"},
    {"id": "+15%", "name": "Nhanh (+15%)"},
    {"id": "+20%", "name": "Nhanh (+20%)"},
]

# Global list of available TTS pitch offsets
AVAILABLE_PITCHES = [
    {"id": "-5Hz", "name": "Thấp (-5Hz)"},
    {"id": "+0Hz", "name": "Mặc định (+0Hz)"},
    {"id": "+2Hz", "name": "Thanh hơn (+2Hz)"},
    {"id": "+5Hz", "name": "Cao (+5Hz)"},
]

# Emotion Preset settings for voice rate, pitch, and BGM mappings
EMOTION_PRESETS = {
    "funny": {"rate": "+8%", "pitch": "+4Hz", "bgm": "funny_loop"},
    "sad": {"rate": "-10%", "pitch": "-5Hz", "bgm": "sad_loop"},
    "drama": {"rate": "-4%", "pitch": "-3Hz", "bgm": "dramatic_loop"},
    "serious": {"rate": "-5%", "pitch": "-2Hz", "bgm": None},
    "energetic": {"rate": "+10%", "pitch": "+3Hz", "bgm": None}
}



# Add bundled ffmpeg/bin to PATH to ensure ffprobe/ffmpeg processes are found globally
ffmpeg_bin = settings.auto_tool_root / "_internal" / "vendor" / "ffmpeg" / "bin"
if ffmpeg_bin.exists():
    os.environ["PATH"] = str(ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")

# Self-healing: Check if ffmpeg exists in PATH. If not, scan WinGet directories to avoid restarting IDE
import shutil
if not shutil.which("ffmpeg"):
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        winget_packages = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
        if winget_packages.exists():
            for folder in winget_packages.glob("Gyan.FFmpeg*"):
                ffmpeg_exes = list(folder.rglob("ffmpeg.exe"))
                if ffmpeg_exes:
                    ffmpeg_dir = ffmpeg_exes[0].parent
                    os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")
                    break

