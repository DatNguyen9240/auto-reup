import os
import json
import shutil
from pathlib import Path
from typing import Any

def ensure_dir(path: Path) -> Path:
    """Ensures a directory exists."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

def write_json(filepath: Path, data: Any):
    """Writes a dictionary/list to a file atomically."""
    fp = Path(filepath)
    ensure_dir(fp.parent)
    
    tmp_file = fp.with_suffix(fp.suffix + ".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    # Atomic rename
    if os.path.exists(fp):
        os.remove(fp)
    shutil.move(str(tmp_file), str(fp))
