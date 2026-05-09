#!/bin/bash
# Dragun — Google Cloud Run deployment script
# Run once to deploy; run again to redeploy with latest code.
#
# Prerequisites (one-time):
#   brew install google-cloud-sdk
#   gcloud auth login
#   gcloud auth configure-docker us-central1-docker.pkg.dev
#
# Usage:
#   bash deploy.sh <YOUR_GCP_PROJECT_ID> <YOUR_GEMINI_API_KEY> [PASSKEY_SALT] [ARIZE_API_KEY]

set -euo pipefail

PROJECT_ID="${1:-}"
GEMINI_API_KEY="${2:-}"

# PASSKEY_SALT must never change after first deploy — it's the key that hashes all passwords.
# If a third arg is given, use it. Otherwise try to read the existing value from Cloud Run.
# Only generate a new random salt if the service doesn't exist yet (first deploy).
if [[ -n "${3:-}" ]]; then
  PASSKEY_SALT="$3"
else
  EXISTING_SALT=$(gcloud run services describe dragun --region us-central1 \
    --format "value(spec.template.spec.containers[0].env)" 2>/dev/null \
    | tr ',' '\n' | grep DRAGUN_PASSKEY_SALT | cut -d= -f2 || true)
  if [[ -n "$EXISTING_SALT" ]]; then
    PASSKEY_SALT="$EXISTING_SALT"
    echo "ℹ️  Reusing existing PASSKEY_SALT from Cloud Run (logins preserved)"
  else
    PASSKEY_SALT=$(openssl rand -hex 16)
    echo "ℹ️  First deploy — generated new PASSKEY_SALT: $PASSKEY_SALT"
    echo "    Save this somewhere safe in case you ever need to redeploy from scratch."
  fi
fi
REGION="us-central1"
SERVICE="dragun"
REPO="dragun-repo"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$SERVICE"

if [[ -z "$PROJECT_ID" || -z "$GEMINI_API_KEY" ]]; then
  echo "Usage: bash deploy.sh <GCP_PROJECT_ID> <GEMINI_API_KEY> [PASSKEY_SALT]"
  echo ""
  echo "  GCP_PROJECT_ID  — your Google Cloud project ID"
  echo "  GEMINI_API_KEY  — from https://aistudio.google.com/app/apikey"
  echo "  PASSKEY_SALT    — optional random salt (auto-generated if omitted)"
  exit 1
fi

echo ""
echo "🐉 Dragun — Cloud Run deployment"
echo "   Project : $PROJECT_ID"
echo "   Region  : $REGION"
echo "   Image   : $IMAGE"
echo ""

# ── 1. Set project ──────────────────────────────────────────────────────────
gcloud config set project "$PROJECT_ID"

# ── 2. Enable required APIs ─────────────────────────────────────────────────
echo "→ Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  --quiet

# ── 2b. Grant Cloud Run SA Vertex AI access ──────────────────────────────────
echo "→ Granting Vertex AI User role to Cloud Run service account..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/aiplatform.user" \
  --quiet 2>/dev/null || true

# ── 3. Create Artifact Registry repo (idempotent) ───────────────────────────
echo "→ Creating Artifact Registry repo..."
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --quiet 2>/dev/null || true

# ── 4. Create Firestore database (idempotent) ───────────────────────────────
echo "→ Setting up Firestore..."
gcloud firestore databases create \
  --location="$REGION" \
  --quiet 2>/dev/null || true

# ── 5. Build & push Docker image ────────────────────────────────────────────
echo "→ Building image..."
gcloud builds submit \
  --tag "$IMAGE" \
  --quiet

# ── 6. Deploy to Cloud Run ──────────────────────────────────────────────────
echo "→ Deploying to Cloud Run..."
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 10 \
  --set-env-vars "\
GOOGLE_CLOUD_PROJECT=$PROJECT_ID,\
DRAGUN_USE_FIRESTORE=true,\
FIRESTORE_DATABASE=(default),\
ADK_MODEL=gemini-2.5-flash,\
GOOGLE_API_KEY=$GEMINI_API_KEY,\
DRAGUN_PASSKEY_SALT=$PASSKEY_SALT,\
CORS_ORIGINS=[\"*\"],\
ARIZE_API_KEY=${4:-}" \
  --quiet

# ── 7. Print URL ─────────────────────────────────────────────────────────────
URL=$(gcloud run services describe "$SERVICE" \
  --region "$REGION" \
  --format "value(status.url)")

echo ""
echo "════════════════════════════════════════"
echo "🐉 Dragun is live!"
echo "   $URL"
echo "════════════════════════════════════════"
echo ""
echo "PASSKEY_SALT used: $PASSKEY_SALT"
echo "Save this — you'll need it if you redeploy."
echo ""
