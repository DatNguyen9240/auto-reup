import os
import json
import shutil
import time
from pathlib import Path
from typing import Any

def ensure_dir(path: Path) -> Path:
    """Ensures a directory exists."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

def write_json(filepath: Path, data: Any, retries: int = 15, delay: float = 0.05):
    """Writes a dictionary/list to a file atomically with retries for Windows file locking."""
    fp = Path(filepath)
    ensure_dir(fp.parent)
    
    tmp_file = fp.with_suffix(fp.suffix + ".tmp")
    
    # Write to tmp file first with retries
    for i in range(retries):
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            break
        except (PermissionError, OSError) as e:
            if i == retries - 1:
                raise
            time.sleep(delay)
        
    # Atomic rename/move with retries
    for i in range(retries):
        try:
            if os.path.exists(fp):
                os.remove(fp)
            shutil.move(str(tmp_file), str(fp))
            return
        except (PermissionError, OSError) as e:
            if i == retries - 1:
                # Try to clean up tmp file if final attempt fails
                try:
                    if os.path.exists(tmp_file):
                        os.remove(tmp_file)
                except Exception:
                    pass
                raise
            time.sleep(delay)

def read_json(filepath: Path, retries: int = 15, delay: float = 0.05) -> Any:
    """Reads a dictionary/list from a JSON file with retries for Windows file locking."""
    fp = Path(filepath)
    for i in range(retries):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except (PermissionError, OSError, json.JSONDecodeError) as e:
            if i == retries - 1:
                raise
            time.sleep(delay)

