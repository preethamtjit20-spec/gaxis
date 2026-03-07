#!/bin/bash
# G-Axis — Cloud Run deployment script
# Usage: ./deploy.sh <PROJECT_ID> [REGION]

set -euo pipefail

PROJECT_ID="${1:?Usage: ./deploy.sh <PROJECT_ID> [REGION]}"
REGION="${2:-us-central1}"
SERVICE_NAME="gaxis"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "=== G-Axis Cloud Run Deployment ==="
echo "Project: ${PROJECT_ID}"
echo "Region:  ${REGION}"
echo ""

# Build frontend first
echo "[1/4] Building frontend..."
cd frontend && npm install && npm run build && cd ..

# Build Docker image
echo "[2/4] Building Docker image..."
gcloud builds submit --tag "${IMAGE}" --project "${PROJECT_ID}"

# Deploy to Cloud Run
echo "[3/4] Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --platform managed \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},HEADLESS=true" \
    --set-secrets "GOOGLE_API_KEY=gaxis-gemini-key:latest"

# Get URL
echo ""
echo "[4/4] Deployment complete!"
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --format="value(status.url)")
echo "URL: ${SERVICE_URL}"
echo ""
echo "To set up the Gemini API key secret:"
echo "  echo -n 'YOUR_KEY' | gcloud secrets create gaxis-gemini-key --data-file=- --project=${PROJECT_ID}"
