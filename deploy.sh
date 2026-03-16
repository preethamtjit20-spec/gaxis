#!/bin/bash
# G-Axis — Cloud Run deployment script
# Usage: ./deploy.sh <PROJECT_ID> [REGION]
#
# Prerequisites:
#   - gcloud CLI authenticated: gcloud auth login
#   - Docker or Cloud Build enabled
#   - Gemini API key stored in Secret Manager (see below)

set -euo pipefail

PROJECT_ID="${1:?Usage: ./deploy.sh <PROJECT_ID> [REGION]}"
REGION="${2:-us-central1}"
SERVICE_NAME="gaxis"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║      G-Axis Cloud Deployment         ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "  Project: ${PROJECT_ID}"
echo "  Region:  ${REGION}"
echo "  Service: ${SERVICE_NAME}"
echo ""

# Step 1: Enable required APIs
echo "[1/5] Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  --project "${PROJECT_ID}" 2>/dev/null || true

# Step 2: Create secret if not exists
echo "[2/5] Checking Gemini API key secret..."
if ! gcloud secrets describe gaxis-gemini-key --project "${PROJECT_ID}" &>/dev/null; then
  echo "  Secret 'gaxis-gemini-key' not found."
  echo "  Create it with:"
  echo "    echo -n 'YOUR_GEMINI_API_KEY' | gcloud secrets create gaxis-gemini-key --data-file=- --project=${PROJECT_ID}"
  echo ""
  read -p "  Enter your Gemini API key (or press Enter to skip): " API_KEY
  if [ -n "${API_KEY}" ]; then
    echo -n "${API_KEY}" | gcloud secrets create gaxis-gemini-key \
      --data-file=- --project="${PROJECT_ID}"
    echo "  Secret created."
  else
    echo "  Skipping — deploy will fail without the secret."
  fi
else
  echo "  Secret exists."
fi

# Step 3: Build Docker image via Cloud Build
echo "[3/5] Building Docker image..."
gcloud builds submit \
  --tag "${IMAGE}" \
  --project "${PROJECT_ID}" \
  --timeout=600

# Step 4: Deploy to Cloud Run
echo "[4/5] Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --min-instances 0 \
  --max-instances 3 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},HEADLESS=true" \
  --set-secrets "GOOGLE_API_KEY=gaxis-gemini-key:latest"

# Step 5: Get deployed URL
echo ""
echo "[5/5] Deployment complete!"
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --format="value(status.url)")

echo ""
echo "╔══════════════════════════════════════╗"
echo "║          Deployment Success          ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "  Backend URL: ${SERVICE_URL}"
echo "  Health:      ${SERVICE_URL}/health"
echo "  Agent Card:  ${SERVICE_URL}/.well-known/agent.json"
echo ""
echo "  Update your extension settings with this URL."
echo ""
