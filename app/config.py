import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # API Configuration
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    
    # Path Configuration
    default_output_folder: str = "./examples/outputs"
    default_music_folder: str = "./examples/music"
    default_source_folder: str = ""
    
    # Render & Pipeline Configuration
    default_voice: str = "vi-VN-HoaiMyNeural" # edge-tts voice ID
    default_rate: str = "+0%"
    default_pitch: str = "+0Hz"
    
    # Audio ducking default volumes
    original_volume: float = 0.25
    tts_volume: float = 1.0
    bgm_volume: float = 0.08
    
    # App root folder
    auto_tool_root: Path = Path(__file__).resolve().parent.parent

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Add bundled ffmpeg/bin to PATH to ensure ffprobe/ffmpeg processes are found globally
ffmpeg_bin = settings.auto_tool_root / "_internal" / "vendor" / "ffmpeg" / "bin"
if ffmpeg_bin.exists():
    os.environ["PATH"] = str(ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")

