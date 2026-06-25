from abc import ABC, abstractmethod
from pathlib import Path

class TTSProvider(ABC):
    @abstractmethod
    async def generate_tts(self, text: str, output_path: Path, voice: str, rate: str, pitch: str) -> Path:
        """Generates a TTS audio file for a given piece of text.
        
        Args:
            text: The text to be converted to speech.
            output_path: The target filepath to save the audio.
            voice: Voice ID or name (e.g., edge-tts voice ID).
            rate: Speaking rate adjustment (e.g., '+0%', '+10%').
            pitch: Speaking pitch adjustment (e.g., '+0Hz').
            
        Returns:
            The Path to the generated audio file.
        """
        pass
