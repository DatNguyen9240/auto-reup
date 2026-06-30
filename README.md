# Auto-Reup Video Studio

Hệ thống tự động hóa tải, dịch thuật, lồng tiếng, và tối ưu hóa video đa nền tảng phục vụ thị trường quốc tế (Facebook Reels, YouTube Shorts, và YouTube Video).

---

## 🚀 Chức Năng Chính

1. **Tải Video Đa Nguồn**: Hỗ trợ tải tự động từ Douyin, Bilibili, YouTube, TikTok hoặc nhập tệp tin video cục bộ.
2. **Nhận Diện Giọng Nói & Chữ (ASR & OCR)**: Tự động trích xuất lời thoại bằng Faster-Whisper AI hoặc nhận dạng chữ phụ đề cũ bằng EasyOCR / PaddleOCR.
3. **Dịch Thuật Bản Địa Hóa (Gemini AI)**:
   * Chỉnh sửa lỗi chính tả ASR tiếng Trung.
   * Dịch thuật theo 3 chế độ chuyên sâu: **Sát nghĩa** (Literal), **Tự nhiên** (Natural), và **Bản địa hóa** (Localized / Viral style - dịch lóng, meme, tương đồng văn hóa).
   * Giới hạn độ dài phụ đề tối đa 2 dòng tự động.
4. **Lồng Tiếng AI Chuẩn Xác (Voice Resolver)**: Tự động chuyển đổi giọng nói EdgeTTS phù hợp theo quốc gia đích (Anh, Tây Ban Nha, Bồ Đào Nha, Nga, Thái, Indonesia, Nhật, Hàn, Việt).
5. **Trộn Âm Thanh (Audio Mixer)**: Điều chỉnh âm lượng, tự động giảm nhạc nền (audio ducking) khi có giọng đọc AI.
6. **Cắt Khung Hình Kéo Thả (Manual Crop)**: Hỗ trợ overlay khung crop 9:16 kéo thả trực quan trên video ngang (Bilibili) để render định dạng Shorts/Reels mà không bị lệch phụ đề.
7. **Kết Xuất Song Song Đa Định Dạng (Multi-Format)**: Xuất đồng thời các định dạng:
   * `fb_reels` (9:16, 1080x1920)
   * `yt_shorts` (9:16, 1080x1920)
   * `yt_video` (16:9, 1920x1080)
8. **Viết SEO Captions tự động**: Gemini AI phân tích câu thoại để tự tạo tiêu đề, mô tả và hashtags chuẩn SEO bằng ngôn ngữ đích lưu vào tệp `caption.txt`.
9. **Tối Giản Thư Mục & Khôi Phục Thông Minh**: Tự động dọn sạch các tệp trung gian (các mảnh audio, tts tạm, video nguồn) sau khi thành công. Khôi phục danh sách phụ đề chỉnh sửa linh hoạt từ file SRT nếu cần rerun.

---

## 🛠️ Công Cụ & Công Nghệ Sử Dụng

### Backend
* **Python 3.10+**: Ngôn ngữ lập trình lõi.
* **FastAPI & Uvicorn**: Framework xây dựng các Web API hiệu năng cao.
* **Pydantic v2**: Xác thực và quản lý mô hình dữ liệu.

### AI & Media Processing
* **Google Gemini API (gemini-2.5-flash)**: Dịch thuật ngữ cảnh lớn, viết captions SEO.
* **Faster-Whisper**: Công cụ nhận dạng giọng nói ASR tốc độ cao.
* **EasyOCR & PaddleOCR**: Nhận diện chữ viết phục vụ che phụ đề gốc.
* **Edge-TTS**: Thư viện sinh giọng đọc AI tự nhiên chất lượng cao.
* **FFmpeg**: Công cụ giải mã, cắt, ghép, trộn âm thanh và render video.
* **yt-dlp & Playwright**: Trình tải video và giả lập trình duyệt tải trang tự động.

### Frontend
* **HTML5 & Vanilla JavaScript**: Quản lý logic tương tác, kéo thả vị trí phụ đề, chọn vùng làm mờ.
* **Tailwind CSS**: Thiết kế giao diện Glassmorphism hiện đại, chuyên nghiệp.
* **Mermaid.js**: Hiển thị sơ đồ luồng dữ liệu tiến trình trực quan.
