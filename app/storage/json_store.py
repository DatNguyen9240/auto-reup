import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from app.models.job import Job
from app.models.segment import Segment
from app.utils.file_utils import write_json

class JsonStore:
    def __init__(self, projects_dir: Path):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        
    def get_job_dir(self, job_id: str) -> Path:
        return self.projects_dir / job_id
        
    def save_job(self, job: Job):
        job.updated_at = datetime.utcnow().isoformat()
        job_dir = self.get_job_dir(job.job_id)
        state_file = job_dir / "job_state.json"
        write_json(state_file, job.model_dump())
        
    def load_job(self, job_id: str) -> Optional[Job]:
        state_file = self.get_job_dir(job_id) / "job_state.json"
        if not state_file.exists():
            return None
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return Job(**data)
            
    def save_transcript(self, job_id: str, segments: List[Segment]):
        filepath = self.get_job_dir(job_id) / "work" / "transcript.json"
        data = [s.model_dump() for s in segments]
        write_json(filepath, data)
        
    def load_transcript(self, job_id: str) -> List[Segment]:
        filepath = self.get_job_dir(job_id) / "work" / "transcript.json"
        if not filepath.exists():
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [Segment(**s) for s in data]
            
    def save_translated(self, job_id: str, segments: List[Segment]):
        filepath = self.get_job_dir(job_id) / "work" / "translated.json"
        data = [s.model_dump() for s in segments]
        write_json(filepath, data)
        
    def load_translated(self, job_id: str) -> List[Segment]:
        filepath = self.get_job_dir(job_id) / "work" / "translated.json"
        if not filepath.exists():
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [Segment(**s) for s in data]
