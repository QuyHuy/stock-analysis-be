# Hướng dẫn Chạy Local

## Yêu cầu

- Python >= 3.12
- pip

## 1. Clone và setup môi trường

```bash
git clone https://github.com/YOUR_ORG/stock-analysis-be.git
cd stock-analysis-be
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Cấu hình `.env`

```bash
cp .env.example .env
```

Điền các giá trị vào `.env`:

- `FIREBASE_PROJECT_ID`: ID project Firebase của bạn
- `FIREBASE_PRIVATE_KEY`: Lấy từ Firebase Console → Project Settings → Service accounts → Generate new private key
- `FIREBASE_CLIENT_EMAIL`: Lấy từ cùng file JSON trên
- `GEMINI_API_KEY`: Lấy từ https://aistudio.google.com/apikey
- `TELEGRAM_BOT_TOKEN`: Lấy từ @BotFather trên Telegram (tùy chọn)

## 3. Chạy server

```bash
uvicorn app.main:app --reload --port 8080
```

API docs: http://localhost:8080/docs

## 4. Chạy tests

```bash
pytest -v
```

## 5. Sync dữ liệu lần đầu

Sau khi server đang chạy, trigger sync:

```bash
curl -X POST http://localhost:8080/sync
```

Chờ ~2-5 phút để sync 50 cổ phiếu.
