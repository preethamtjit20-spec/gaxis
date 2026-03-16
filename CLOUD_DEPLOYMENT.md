# G-Axis — Google Cloud Deployment Proof

## Live Deployment

**Cloud Run URL**: https://gaxis-132388856648.us-central1.run.app

| Endpoint | URL |
|----------|-----|
| Health Check | https://gaxis-132388856648.us-central1.run.app/health |
| Agent Card | https://gaxis-132388856648.us-central1.run.app/.well-known/agent.json |
| Dashboard API | https://gaxis-132388856648.us-central1.run.app/api/dashboard |

## Google Cloud Services Used

### 1. Cloud Run (Serverless Hosting)
- **Service**: `gaxis` in `us-central1`
- **Config**: 2 vCPU, 2GB RAM, min=1 max=3 instances, autoscaling
- **Image**: `gcr.io/gaxis-488323/gaxis:latest`

### 2. Secret Manager (API Key Storage)
- **Secret**: `gaxis-gemini-key`
- Gemini API key stored securely, injected at runtime via `--set-secrets`
- Never exposed in code, git, or network endpoints
- Backend generates short-lived OAuth2 access tokens via `/api/v`

### 3. Cloud Build (CI/CD)
- Docker image built via `gcloud builds submit`
- Base: `python:3.12-slim` + Playwright + Chromium
- Pushed to Google Container Registry (GCR)

### 4. Terraform (Infrastructure as Code)
- Full IaC in [`terraform/main.tf`](terraform/main.tf)
- Provisions: APIs, Cloud Run, Secret Manager, IAM, Cloud Scheduler
- Scheduled jobs: Daily analysis (midnight UTC), Weekly reports (Sunday 11PM UTC)

## Deployment Files

| File | Purpose |
|------|---------|
| [`terraform/main.tf`](terraform/main.tf) | Terraform IaC — all GCP resources |
| [`deploy.sh`](deploy.sh) | Automated deployment script (APIs + Secret + Build + Deploy) |
| [`Dockerfile`](Dockerfile) | Cloud Run container definition |
| [`backend/main.py`](backend/main.py) | OAuth2 token generation (`google.auth`) |

## Deployment Commands Used

```bash
# 1. Enable APIs
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

# 2. Store API key in Secret Manager
echo -n 'KEY' | gcloud secrets create gaxis-gemini-key --data-file=-

# 3. Grant Secret access to Cloud Run service account
gcloud secrets add-iam-policy-binding gaxis-gemini-key \
  --member="serviceAccount:132388856648-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# 4. Build Docker image via Cloud Build
gcloud builds submit --tag gcr.io/gaxis-488323/gaxis

# 5. Deploy to Cloud Run
gcloud run deploy gaxis \
  --image gcr.io/gaxis-488323/gaxis \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 \
  --min-instances 1 --max-instances 3 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=gaxis-488323,HEADLESS=true" \
  --set-secrets "GOOGLE_API_KEY=gaxis-gemini-key:latest"
```

## GCP Project
- **Project ID**: `gaxis-488323`
- **Region**: `us-central1`
- **Service Account**: `132388856648-compute@developer.gserviceaccount.com`
