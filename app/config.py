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
    
    # Channel Configuration
    channel_name: str = Field(default="AutoTool Review", validation_alias="CHANNEL_NAME")
    
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

