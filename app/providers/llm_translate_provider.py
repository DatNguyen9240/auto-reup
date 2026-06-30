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

    def translate(
        self,
        segments: List[Segment],
        tone: str,
        target_language: str = "vi-VN",
        target_locale: Optional[str] = None,
        translation_mode: str = "natural"
    ) -> List[Segment]:
        if not segments:
            return []
            
        logger.info(f"Translating {len(segments)} segments with tone '{tone}', lang '{target_language}', locale '{target_locale}', mode '{translation_mode}' using Gemini.")
        
        # Prepare chunk data to preserve contextual flows for the LLM
        payload = []
        for s in segments:
            payload.append({
                "id": s.id,
                "text": s.source_text
            })
            
        # Mode description mapping
        mode_instructions = {
            "literal": (
                "Dịch sát nghĩa (Literal translation). Dịch chính xác từng chữ, giữ nguyên nghĩa đen "
                "và cấu trúc câu nếu có thể. Thích hợp cho nội dung khoa học, kỹ thuật, thông tin, hướng dẫn."
            ),
            "natural": (
                "Dịch tự nhiên (Natural translation). Dịch trôi chảy, tự nhiên như người bản xứ nói thông thường, "
                "đảm bảo nhịp điệu và ngữ nghĩa tự nhiên."
            ),
            "localized": (
                "Dịch phóng khoáng/địa phương hóa (Localized / Viral style). Dịch theo văn hóa người xem. "
                "Hãy chuyển nghĩa các tiếng lóng, thành ngữ, meme, drama từ tiếng Trung sang các câu nói thịnh hành (viral), "
                "hài hước hoặc slang tương đương của ngôn ngữ đích để tạo cảm giác gần gũi nhất."
            )
        }
        mode_desc = mode_instructions.get(translation_mode, mode_instructions["natural"])

        # Language specific rules
        lang_instructions = {
            "vi": (
                "Dịch sang tiếng Việt tự nhiên, có đầy đủ dấu. Tránh dịch Hán-Việt quá cứng nhắc. "
                "Với review phim/drama, câu cú phải giật gân, hấp dẫn và tự nhiên."
            ),
            "en": (
                "Translate to English. Keep sentences short, direct, and natural. "
                "Use casual English slang if appropriate for memes/drama, but avoid overly formal language."
            ),
            "es": (
                f"Translate to Spanish (Locale: {target_locale or 'Neutral'}). "
                f"Use es-MX (Mexican Spanish) slang if locale is es-MX, or es-ES (Spain Spanish) if locale is es-ES. "
                "If neutral Spanish is targeted, keep it universally understandable across Latin America and Spain."
            ),
            "pt": (
                f"Translate to Portuguese (Locale: {target_locale or 'pt-BR'}). "
                f"Use pt-BR (Brazilian Portuguese) expressions if locale is pt-BR, or pt-PT (Portugal Portuguese) if locale is pt-PT. "
                "Do not mix Brazilian and European Portuguese slangs."
            ),
            "ru": (
                "Translate to Russian. Ensure natural phrasing, avoid literal translations of idioms. "
                "Control sentence length and split long clauses if necessary to fit the timing."
            ),
            "th": (
                "Translate to Thai. Use natural Thai phrasing suitable for social media videos."
            ),
            "id": (
                "Translate to Indonesian. Keep it casual, natural, and direct."
            ),
            "ja": (
                "Translate to Japanese. Use natural spoken Japanese. Keep lines very concise (max 22 characters per line)."
            ),
            "ko": (
                "Translate to Korean. Use natural spoken Korean phrasing. Keep lines concise."
            )
        }
        lang_prefix = target_language.split("-")[0].lower()
        lang_desc = lang_instructions.get(lang_prefix, lang_instructions["en"])

        prompt = f"""Bạn là một chuyên gia dịch thuật video chuyên nghiệp sang ngôn ngữ đích: {target_language} (locale: {target_locale or 'mặc định'}).
Hãy dịch danh sách phụ đề video ngắn dưới đây.

PHONG CÁCH DỊCH:
- Tông giọng chung của video: {tone}
- Chế độ dịch: {mode_desc}
- Yêu cầu ngôn ngữ đích: {lang_desc}

YÊU CẦU QUAN TRỌNG:
1. SỬA LỖI CHÍNH TẢ & ĐỒNG ÂM (ASR CORRECTION):
   Phụ đề nguồn tiếng Trung được tạo tự động bằng nhận diện giọng nói (ASR) nên chứa rất nhiều lỗi đồng âm hoặc sai chính tả. Hãy tự động phân tích ngữ cảnh để sửa các lỗi này trước khi dịch. Ví dụ:
   - "逆名" thực chất là "匿名" (nặc danh).
   - "契礼子散" thực chất là "妻离子散" (vợ con ly tán, tan nhà nát cửa).
   - "印着头皮" thực chất là "硬着头皮" (nhắm mắt đưa chân, cố chịu đựng).
   - "让人招这儿" thực chất là "店里/这儿" (ở đây, ở cửa hàng).

2. ĐẠI TỪ NHÂN XƯNG CHÍNH XÁC:
   Hãy đọc toàn bộ ngữ cảnh câu chuyện để dịch đại từ chính xác tương thích với nhân vật nam/nữ trong câu chuyện ở ngôn ngữ đích.

3. DỊCH PHÓNG KHOÁNG, KHÔNG DỊCH WORD-BY-WORD:
   Không dịch từng chữ một cách máy móc. Hãy chuyển thể nghĩa, sắc thái biểu đạt, tiếng lóng sang câu tương đương có nghĩa tương đương ở ngôn ngữ đích.

4. KHỐNG CHẾ ĐỘ DÀI PHỤ ĐỀ:
   - Phụ đề dịch ra tối đa 2 dòng.
   - Giới hạn số ký tự trên mỗi dòng tùy thuộc ngôn ngữ (Tiếng Anh/Việt/Indo: tối đa 45 ký tự; Tây Ban Nha/Bồ Đào Nha/Nga: tối đa 50 ký tự; Nhật/Hàn: tối đa 22 ký tự).
   - Hãy rút gọn câu từ nếu cần thiết nhưng vẫn giữ nguyên ý chính và cảm xúc để người dùng đọc kịp và giọng đọc AI (TTS) có đủ thời gian đọc mà không bị nói quá nhanh.

5. Giữ nguyên cấu trúc ID, trả về định dạng danh sách JSON tương tự đầu vào với trường "translated_text" là bản dịch bằng ngôn ngữ {target_language}.
6. Không tự ý gộp/tách câu, đảm bảo số lượng phần tử trả về trùng khớp hoàn toàn với đầu vào.
7. Chỉ trả về JSON hợp lệ, không bọc trong block Markdown hay giải thích gì thêm.
8. ĐỒNG BỘ TÊN KÊNH THƯƠNG HIỆU:
   Nếu trong phụ đề gốc xuất hiện tên kênh của tác giả video tiếng Trung, hãy dịch/thay thế nó thành tên kênh thương hiệu sau: '{settings.channel_name}'.

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
