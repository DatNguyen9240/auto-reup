import os
import sys
from pathlib import Path

def project_root() -> Path:
    """Returns root directory of the AutoTool project."""
    return Path(__file__).resolve().parent.parent.parent

def app_data_dir() -> Path:
    """Returns local app data directory for storing config and database."""
    base_dir = Path(os.environ.get("AUTO_TOOL_DATA_DIR", "~/.autotool")).expanduser()
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir

def frontend_dist_dir() -> Path:
    """Returns frontend distribution folder."""
    fallback_dist = project_root() / "_internal" / "frontend" / "dist"
    env_dist = os.environ.get("AUTO_TOOL_FRONTEND_DIST")
    if env_dist:
        return Path(env_dist)
    return fallback_dist

def bundled_vendor_dir() -> Path:
    """Returns directory where FFmpeg and other vendor tools are located."""
    return project_root() / "_internal" / "vendor"
