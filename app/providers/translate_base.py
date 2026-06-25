from abc import ABC, abstractmethod
from typing import List
from app.models.segment import Segment

class TranslateProvider(ABC):
    @abstractmethod
    def translate(self, segments: List[Segment], tone: str) -> List[Segment]:
        """Translates the source_text in a list of segments into translated_text.
        
        Args:
            segments: List of Segments with source_text populated.
            tone: The style or tone of translation (e.g. 'review_phim', 'docs', 'funny').
            
        Returns:
            The list of Segments with translated_text populated.
        """
        pass
