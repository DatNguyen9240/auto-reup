import os
import logging
import sys
from pathlib import Path

def configure_logging(log_file: str = None):
    """Configures global logging system."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=handlers,
        force=True
    )

import threading
from typing import Optional

_local = threading.local()

def set_current_job_id(job_id: Optional[str]):
    """Sets the current job ID for the active thread."""
    _local.job_id = job_id

def get_current_job_id() -> Optional[str]:
    """Retrieves the current job ID for the active thread."""
    return getattr(_local, "job_id", None)

class JobLogFilter(logging.Filter):
    """Filter that only permits logs belonging to a specific job ID."""
    def __init__(self, job_id: str):
        super().__init__()
        self.job_id = job_id

    def filter(self, record) -> bool:
        return get_current_job_id() == self.job_id

def wrap_with_job_context(job_id: Optional[str], func):
    """Wraps a function to execute with the given job ID in its thread-local context."""
    def wrapper(*args, **kwargs):
        set_current_job_id(job_id)
        try:
            return func(*args, **kwargs)
        finally:
            set_current_job_id(None)
    return wrapper

def get_logger(name: str) -> logging.Logger:
    """Returns a logger with the given name."""
    return logging.getLogger(name)
