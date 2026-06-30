# Hướng dẫn cài đặt & sử dụng Reup Video Douyin

## 🚀 Cài đặt lần đầu

### Bước 1: Cài dependencies
```
Bấm đúp file start_server.bat
→ Tự động cài tất cả
```

Hoặc chạy thủ công:
```bash
pip install -r requirements.txt
```

### Bước 2: Chạy server
```
Bấm đúp start_server.bat
```

Hoặc:
```bash
python server.py
```

### Bước 3: Mở trình duyệt
```
http://localhost:8000
```

---

## 📱 Cho bố dùng trên điện thoại (MIỄN PHÍ)

### Cách 1: Ngrok (Dễ nhất)

1. **Tải ngrok**: https://ngrok.com/download
2. **Đăng ký free**: https://dashboard.ngrok.com/signup
3. **Lấy authtoken** từ dashboard, chạy:
   ```bash
   ngrok config add-authtoken YOUR_TOKEN
   ```
4. **Chạy ngrok** (sau khi start server):
   ```bash
   ngrok http 8000
   ```
5. **Copy link** dạng `https://xxxx-xxx.ngrok-free.app` → gửi cho bố

### Cách 2: Cloudflare Tunnel (Ổn định hơn)

1. **Tải cloudflared**: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
2. **Chạy nhanh** (không cần tài khoản):
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
3. **Copy link** → gửi cho bố

### Cách 3: Cùng WiFi (Đơn giản nhất)

Nếu bố và bạn dùng **cùng WiFi**:
1. Mở CMD, gõ `ipconfig` → tìm **IPv4 Address** (VD: 192.168.1.100)
2. Bố mở Chrome gõ: `http://192.168.1.100:8000`
3. Done!

---

## ⚙️ Tự động chạy khi bật máy tính

1. Nhấn `Win + R`, gõ `shell:startup`, Enter
2. Copy file `start_server.bat` vào thư mục vừa mở
3. Mỗi lần bật máy, server sẽ tự chạy!

---

## 🔧 Ghi chú kỹ thuật

- **Port**: 8000 (mặc định)
- **Whisper model**: `base` (nhẹ, nhanh). Đổi sang `medium` hoặc `large-v3` trong `pipeline.py` nếu cần chính xác hơn
- **Giọng đọc**:
  - Nữ: `vi-VN-HoaiMyNeural`
  - Nam: `vi-VN-NamMinhNeural`
- **Temp files**: Lưu tại thư mục `temp/` - có thể xóa định kỳ
