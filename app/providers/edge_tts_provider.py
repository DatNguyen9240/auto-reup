import edge_tts
from pathlib import Path
from app.providers.tts_base import TTSProvider
from app.core.errors import TTSError
from app.utils.logger import get_logger

logger = get_logger("EdgeTTSProvider")

class EdgeTTSProvider(TTSProvider):
    async def generate_tts(self, text: str, output_path: Path, voice: str, rate: str, pitch: str) -> Path:
        logger.debug(f"Generating TTS for: '{text}' (voice={voice}, rate={rate}, pitch={pitch})")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if not text.strip():
            logger.warning("Empty text passed to TTS provider. Creating an empty or silent segment.")
            # edge-tts might fail on empty text. We'll return a path, and handling code will deal with silent audios if needed.
            # But normally we only call TTS for non-empty text.
            
        import asyncio
        for attempt in range(1, 4):
            try:
                communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
                await communicate.save(str(output_path))
                
                if not output_path.exists() or output_path.stat().st_size == 0:
                    raise TTSError("Generated TTS file is empty or does not exist.")
                    
                return output_path
            except Exception as e:
                logger.warning(f"EdgeTTS attempt {attempt} failed: {e}")
                if attempt == 3:
                    logger.error(f"EdgeTTS failed to generate audio after 3 attempts: {e}")
                    raise TTSError(f"EdgeTTS generation failed: {e}")
                await asyncio.sleep(2.0 * attempt)
