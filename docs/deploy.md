# Hướng dẫn Deploy Backend lên Google Cloud Run

## Yêu cầu

- Google Cloud CLI đã cài: https://cloud.google.com/sdk/docs/install
- Docker đã cài
- Firebase project đã tạo (xem Task 1)

## 1. Chuẩn bị GCP Project

```bash
# Set project
gcloud config set project stock-analysis-vn

# Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable cloudscheduler.googleapis.com
gcloud services enable secretmanager.googleapis.com

# Create Artifact Registry repository
gcloud artifacts repositories create stock-analysis \
  --repository-format=docker \
  --location=asia-southeast1
```

## 2. Tạo Secret cho Firebase Private Key

`FIREBASE_PRIVATE_KEY` là chuỗi nhiều dòng (PEM format) — không thể truyền qua
`--set-env-vars` một cách an toàn. Thay vào đó, lưu vào Google Secret Manager và
dùng `--set-secrets` trong workflow.

```bash
# Lấy private_key từ Service Account JSON, paste vào file tạm
echo "-----BEGIN PRIVATE KEY-----
YOUR_KEY_HERE
-----END PRIVATE KEY-----" | gcloud secrets create firebase-private-key \
  --data-file=- \
  --replication-policy=automatic
```

Cloud Run sẽ mount secret này tự động khi deploy (xem `deploy-be.yml`).

## 3. Tạo Service Account cho CI/CD

```bash
# Tạo SA
gcloud iam service-accounts create github-actions \
  --display-name="GitHub Actions CI/CD"

SA_EMAIL="github-actions@stock-analysis-vn.iam.gserviceaccount.com"

# Gán roles
gcloud projects add-iam-policy-binding stock-analysis-vn \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding stock-analysis-vn \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding stock-analysis-vn \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding stock-analysis-vn \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/secretmanager.secretAccessor"

# Tạo key JSON
gcloud iam service-accounts keys create gcp-sa-key.json \
  --iam-account=$SA_EMAIL
```

## 4. Thêm GitHub Secrets

Trong GitHub repo → Settings → Secrets and variables → Actions:

| Secret | Value |
|--------|-------|
| `GCP_SA_KEY` | Nội dung file `gcp-sa-key.json` |
| `FIREBASE_PROJECT_ID` | `stock-analysis-vn` |
| `FIREBASE_CLIENT_EMAIL` | email của Firebase service account |
| `GEMINI_API_KEY` | API key từ Google AI Studio |
| `TELEGRAM_BOT_TOKEN` | Token từ @BotFather |
| `ALLOWED_ORIGINS` | `https://your-app.vercel.app` |

> **Xóa `gcp-sa-key.json` sau khi thêm vào GitHub Secrets!**

## 5. Deploy lần đầu

```bash
# Push to main branch để trigger GitHub Actions
git push origin main
```

Theo dõi workflow tại: https://github.com/YOUR_ORG/stock-analysis-be/actions

## 6. Thiết lập Cloud Scheduler

Sau khi deploy thành công, lấy Cloud Run URL từ:

```bash
gcloud run services describe stock-analysis-be \
  --region=asia-southeast1 \
  --format="value(status.url)"
```

Tạo Cloud Scheduler jobs:

```bash
CLOUD_RUN_URL="https://YOUR-CLOUD-RUN-URL"

# Sync dữ liệu hàng ngày lúc 18:00 VN (11:00 UTC) - thứ 2 đến thứ 6
gcloud scheduler jobs create http sync-daily \
  --schedule="0 11 * * 1-5" \
  --uri="${CLOUD_RUN_URL}/sync" \
  --http-method=POST \
  --location=asia-southeast1 \
  --time-zone="Asia/Ho_Chi_Minh" \
  --attempt-deadline=30m

# Kiểm tra alerts mỗi 15 phút trong giờ giao dịch (9:00-14:45 VN)
gcloud scheduler jobs create http check-alerts \
  --schedule="*/15 2-8 * * 1-5" \
  --uri="${CLOUD_RUN_URL}/alerts/check" \
  --http-method=POST \
  --location=asia-southeast1 \
  --time-zone="Asia/Ho_Chi_Minh"
```

## 7. Kiểm tra sau deploy

```bash
curl https://YOUR-CLOUD-RUN-URL/health
# Expected: {"status": "ok"}
```
