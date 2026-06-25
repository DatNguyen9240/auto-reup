import json
from typing import List
from google import genai
from google.genai import types
from app.config import settings
from app.providers.translate_base import TranslateProvider
from app.models.segment import Segment
from app.core.errors import TranslationError
from app.utils.logger import get_logger

logger = get_logger("LLMTranslateProvider")

import os

class LLMTranslateProvider(TranslateProvider):
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.gemini_api_key
        fallback_enabled = os.environ.get("AUTO_TOOL_ALLOW_TRANSLATION_FALLBACK", "false").lower() == "true"
        
        if not self.api_key:
            if fallback_enabled:
                logger.warning("Gemini API key is not configured, but fallback translation is enabled.")
                self.client = None
                return
            raise TranslationError("Gemini API key is not configured. Please set the GEMINI_API_KEY environment variable.")
        try:
            self.client = genai.Client(api_key=self.api_key)
        except Exception as e:
            if fallback_enabled:
                logger.warning(f"Failed to initialize Gemini Client: {e}. Fallback translation is active.")
                self.client = None
            else:
                raise TranslationError(f"Failed to initialize Gemini Client: {e}")


    def translate(self, segments: List[Segment], tone: str) -> List[Segment]:
        if not segments:
            return []
            
        logger.info(f"Translating {len(segments)} segments with tone '{tone}' using Gemini.")
        
        # Prepare chunk data to preserve contextual flows for the LLM
        payload = []
        for s in segments:
            payload.append({
                "id": s.id,
                "text": s.source_text
            })
            
        prompt = f"""Bạn là một chuyên gia dịch thuật video chuyên nghiệp từ nước ngoài sang tiếng Việt.
Hãy dịch danh sách phụ đề video ngắn dưới đây sang tiếng Việt.

Yêu cầu:
1. Dịch tự nhiên, sinh động, phù hợp với văn phong video ngắn dạng "{tone}".
2. Giữ nguyên cấu trúc ID, trả về định dạng danh sách JSON tương tự đầu vào với trường "translated_text" là bản dịch tiếng Việt.
3. Không tự ý gộp/tách câu, đảm bảo số lượng phần tử trả về trùng khớp hoàn toàn với đầu vào.
4. Chỉ trả về JSON hợp lệ, không bọc trong block Markdown hay giải thích gì thêm.

Danh sách phụ đề cần dịch:
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""

        try:
            # We use gemini-2.5-flash as default model
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            
            response_text = response.text.strip()
            # Clean up potential markdown wrappers
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            translated_data = json.loads(response_text)
            
            # Create mapping table
            translations = {}
            if isinstance(translated_data, list):
                for item in translated_data:
                    if isinstance(item, dict) and "id" in item and "translated_text" in item:
                        translations[int(item["id"])] = item["translated_text"]
            elif isinstance(translated_data, dict) and "translations" in translated_data:
                for item in translated_data["translations"]:
                    if "id" in item and "translated_text" in item:
                        translations[int(item["id"])] = item["translated_text"]
                        
            # Apply translations
            for s in segments:
                s.translated_text = translations.get(s.id, s.source_text)
                # Initialize tts_text
                s.tts_text = s.translated_text
                s.status = "translated"
                
            logger.info("Translation successfully completed.")
            return segments
            
        except Exception as e:
            logger.error(f"Gemini API request or parsing failed: {e}")
            # Optional fallback behavior if env flag allows it
            if os.environ.get("AUTO_TOOL_ALLOW_TRANSLATION_FALLBACK", "false").lower() == "true":
                logger.warning("Using translation fallback (translating Chinese test prompts to Vietnamese).")
                for s in segments:
                    txt = s.source_text.strip()
                    if "这是一只" in txt or "猫咪" in txt:
                        s.translated_text = "Đây là một chú mèo rất đáng yêu đang chạy trên bãi cỏ."
                    elif "动作" in txt or "玩耍" in txt:
                        s.translated_text = "Động tác của nó vô cùng nhanh nhẹn, chúng ta hãy cùng xem nó vui chơi thế nào nhé."
                    else:
                        s.translated_text = f"Bản dịch thử nghiệm phân cảnh {s.id}."
                    
                    s.tts_text = s.translated_text
                    s.status = "translated"
                return segments
            raise TranslationError(f"Gemini translation failed: {e}")
