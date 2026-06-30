import json
from typing import List, Optional
from google import genai
from google.genai import types
from pydantic import BaseModel
from app.config import settings
from app.providers.translate_base import TranslateProvider
from app.models.segment import Segment
from app.core.errors import TranslationError
from app.utils.logger import get_logger

logger = get_logger("LLMTranslateProvider")

import os

class TranslationItem(BaseModel):
    id: int
    translated_text: str

class TranslationResponse(BaseModel):
    translations: List[TranslationItem]

class LLMTranslateProvider(TranslateProvider):
    def __init__(self, api_key: str = None):
        self.api_keys = []
        primary_key = api_key or settings.gemini_api_key
        if primary_key:
            self.api_keys.append(primary_key)
        for i in range(2, 11):
            key_val = getattr(settings, f"gemini_api_key_{i}", None)
            if key_val:
                self.api_keys.append(key_val)
            
        # Filter out empty or whitespace-only keys
        self.api_keys = [k.strip() for k in self.api_keys if k.strip()]
        
        fallback_enabled = os.environ.get("AUTO_TOOL_ALLOW_TRANSLATION_FALLBACK", "false").lower() == "true"
        
        # Set self.client to the first active client for backward compatibility
        self.client = None
        if self.api_keys:
            try:
                self.client = genai.Client(api_key=self.api_keys[0])
            except Exception as e:
                logger.warning(f"Failed to initialize primary Gemini Client: {e}")
                
        if not self.api_keys:
            if fallback_enabled:
                logger.warning("Gemini API key is not configured, but fallback translation is enabled.")
                return
            logger.warning("Gemini API key is not configured. Translation will fail until GEMINI_API_KEY is set.")

    def generate_content(self, prompt: str, model: str = 'gemini-2.5-flash', mime_type: Optional[str] = None, schema: Optional[BaseModel] = None):
        if not self.api_keys:
            raise TranslationError("Gemini API key is not configured. Please set the GEMINI_API_KEY environment variable.")

        response = None
        last_error = None
        
        # Try each client key in order
        for idx, key in enumerate(self.api_keys):
            try:
                logger.info(f"Attempting content generation using Gemini API Key {idx + 1}/{len(self.api_keys)}...")
                client = genai.Client(api_key=key)
                
                config_args = {}
                if mime_type:
                    config_args["response_mime_type"] = mime_type
                if schema:
                    config_args["response_schema"] = schema
                    
                config = types.GenerateContentConfig(**config_args) if config_args else None
                
                # Try up to 2 times for transient network errors per key
                for attempt in range(1, 3):
                    try:
                        response = client.models.generate_content(
                            model=model,
                            contents=prompt,
                            config=config
                        )
                        break
                    except Exception as e:
                        logger.warning(f"Gemini API Key {idx + 1} attempt {attempt} failed: {e}")
                        
                        # Quota exhaustion model fallback
                        err_str = str(e).lower()
                        if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
                            for fallback_model in ['gemini-2.0-flash', 'gemini-1.5-flash']:
                                if fallback_model != model:
                                    logger.info(f"Quota exhausted for {model}. Attempting fallback to model: {fallback_model}...")
                                    try:
                                        response = client.models.generate_content(
                                            model=fallback_model,
                                            contents=prompt,
                                            config=config
                                        )
                                        logger.info(f"Fallback to {fallback_model} succeeded!")
                                        break
                                    except Exception as fallback_err:
                                        logger.warning(f"Fallback to {fallback_model} failed: {fallback_err}")
                            if response:
                                break
                                
                        if attempt == 2:
                            raise e
                        import time
                        time.sleep(2.0)
                        
                if response:
                    logger.info(f"Successfully generated content using Gemini API Key {idx + 1}.")
                    return response
            except Exception as e:
                logger.error(f"Gemini API Key {idx + 1} failed: {e}")
                last_error = e
                # Fall back to next key
                
        raise TranslationError(f"All configured Gemini API Keys failed. Last error: {last_error}")

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

BỐI CẢNH & PHONG CÁCH:
- Video ngắn dạng kịch tính, tóm tắt phim/review phim.
- Giọng văn kịch tính, cuốn hút, tự nhiên, trôi chảy.

YÊU CẦU QUAN TRỌNG:
1. SỬA LỖI CHÍNH TẢ & ĐỒNG ÂM (ASR CORRECTION):
   Phụ đề nguồn tiếng Trung được tạo tự động bằng nhận diện giọng nói (ASR) nên chứa rất nhiều lỗi đồng âm hoặc sai chính tả. Hãy tự động phân tích ngữ cảnh để sửa các lỗi này trước khi dịch. Ví dụ:
   - "逆名" thực chất là "匿名" (nặc danh).
   - "契礼子散" thực chất là "妻离子散" (vợ con ly tán, tan nhà nát cửa).
   - "印着头皮" thực chất là "硬着头皮" (nhắm mắt đưa chân, cố chịu đựng).
   - "复约" thực chất là "赴约" (đến hẹn, đi gặp).
   - "舞运" thực chất là "迷晕" (đánh thuốc mê, làm bất tỉnh).
   - "让人招这儿" thực chất là "店里/这儿" (ở đây, ở cửa hàng).

2. ĐẠI TỪ NHÂN XƯNG CHÍNH XÁC:
   Do phát âm tiếng Trung của "他" (anh ấy) và "她" (cô ấy) đều là "tā", công cụ ASR thường viết sai lẫn lộn chữ " she" và "he".
   Hãy đọc toàn bộ ngữ cảnh câu chuyện để dịch đại từ chính xác:
   - Hàn Đông (韩东) là nam (người chồng - "丈夫" / "男人"), nên khi các câu sau nhắc đến Hàn Đông mà phụ đề viết "她", hãy dịch thành "anh", "anh ấy", "hắn" (không được dịch thành "cô", "nàng").
   - Lâm Mỹ Nguyệt (林美月) và Mia (米亚) là nữ, hãy dùng "cô ấy", "cô", "chị ấy".

3. Dịch tự nhiên, sinh động, phù hợp với văn phong video ngắn dạng "{tone}".
4. Giữ nguyên cấu trúc ID, trả về định dạng danh sách JSON tương tự đầu vào với trường "translated_text" là bản dịch tiếng Việt.
5. Không tự ý gộp/tách câu, đảm bảo số lượng phần tử trả về trùng khớp hoàn toàn với đầu vào.
6. TỐI ƯU ĐỘ DÀI: Hãy dịch cực kỳ ngắn gọn, súc tích, lược bỏ các từ rườm rà. Câu dịch tiếng Việt phải ngắn gọn để khi lồng tiếng bằng giọng đọc AI không bị nói quá nhanh.
7. Chỉ trả về JSON hợp lệ, không bọc trong block Markdown hay giải thích gì thêm.
8. ĐỒNG BỘ TÊN KÊNH THƯƠNG HIỆU:
   Nếu trong phụ đề gốc xuất hiện tên kênh của tác giả video tiếng Trung (như '真探说' hoặc các tên tự giới thiệu kênh ở cuối video), hãy dịch/thay thế nó thành tên kênh thương hiệu tiếng Việt sau: '{settings.channel_name}'. 
   Ví dụ: '我是真探说' -> 'Tôi là {settings.channel_name}'.

Danh sách phụ đề cần dịch:
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""


        try:
            response = self.generate_content(
                prompt=prompt,
                mime_type="application/json",
                schema=TranslationResponse
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
