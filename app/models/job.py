from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime

class Job(BaseModel):
    job_id: str
    status: str = "created"
    current_step: str = ""
    input_path: str
    output_path: str = ""
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    steps: Dict[str, str] = Field(default_factory=lambda: {
        "intake": "pending",
        "analyze": "pending",
        "extract_audio": "pending",
        "transcribe": "pending",
        "translate": "pending",
        "tts": "pending",
        "mix_audio": "pending",
        "subtitle_layout": "pending",
        "render": "pending",
        "metadata": "pending"
    })
    errors: List[str] = Field(default_factory=list)
    channel_folder: Optional[str] = None
    platform_folder: Optional[str] = None
    channel_id: Optional[str] = None
    is_published: bool = False
    ocr_only_mode: bool = False
    target_language: str = "vi-VN"
    target_locale: Optional[str] = None
    translation_mode: str = "natural"
    input_width: int = 0
    input_height: int = 0
    input_aspect_ratio: float = 1.0
    input_aspect_type: str = "vertical"
    outputs: Dict[str, Any] = Field(default_factory=dict)
    config_snapshot: Dict[str, Any] = Field(default_factory=dict)
