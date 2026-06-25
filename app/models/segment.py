from pydantic import BaseModel, Field

class Segment(BaseModel):
    id: int
    start_ms: int
    end_ms: int
    speaker: str = "SPEAKER_1"
    source_text: str
    translated_text: str = ""
    tts_text: str = ""
    tts_path: str = ""
    confidence: float = 1.0
    status: str = "pending" # pending, translated, tts_generated, needs_review

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms
