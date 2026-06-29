from pydantic import BaseModel, Field
from typing import Dict, List, Optional
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
        "render": "pending",
        "metadata": "pending"
    })
    errors: List[str] = Field(default_factory=list)
    channel_folder: Optional[str] = None
    platform_folder: Optional[str] = None
    channel_id: Optional[str] = None
