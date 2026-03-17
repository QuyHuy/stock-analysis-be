# Stock Analysis BE

FastAPI backend cho hệ thống phân tích chứng khoán Việt Nam.

## Tính năng

- **RAG Chat API**: Hỏi đáp về cổ phiếu với AI (Gemini) dựa trên dữ liệu thực
- **Stock API**: Tra cứu giá, lịch sử giao dịch 50 cổ phiếu phổ biến
- **Alerts API**: Đặt và quản lý cảnh báo giá, thông báo qua Telegram
- **Auto Sync**: Tự động sync dữ liệu từ vnstock vào Firestore hàng ngày

## Tech Stack

- Python 3.12, FastAPI
- Firebase Admin SDK (Firestore, Auth)
- Google Gemini API (`gemini-2.0-flash`)
- vnstock (dữ liệu chứng khoán VN, miễn phí)
- Telegram Bot API (cảnh báo)
- Google Cloud Run (hosting)

## Bắt đầu nhanh

```bash
cp .env.example .env
# Điền Firebase + Gemini credentials vào .env
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Xem `docs/setup.md` để biết chi tiết.

## Deploy

Xem `docs/deploy.md` để hướng dẫn deploy lên Google Cloud Run.

## API Endpoints

| Method | Path | Mô tả |
|--------|------|-------|
| GET | `/health` | Health check |
| POST | `/chat` | RAG chat với AI |
| GET | `/stocks` | Danh sách mã CK |
| GET | `/stocks/{symbol}` | Chi tiết + lịch sử giá |
| POST | `/alerts` | Tạo cảnh báo giá |
| GET | `/alerts` | Danh sách cảnh báo |
| DELETE | `/alerts/{id}` | Xóa cảnh báo |
| POST | `/alerts/check` | Kiểm tra và gửi cảnh báo |
| POST | `/sync` | Trigger đồng bộ dữ liệu |

API docs: http://localhost:8080/docs (khi chạy local)
