#!/usr/bin/env bash
# Deploy the hackathon demo: one Cloud Run service serving the API and the website.
#
#   bash infra/deploy.sh
#
# Reads non-secret settings from .env. The Gemini key is NOT passed here: it lives in
# Secret Manager as `gemini-api-key` (docs/DEPLOYMENT.md explains the one-time setup),
# so it never appears in the service definition, the image, or shell history.
set -euo pipefail
cd "$(dirname "$0")/.."

get() { sed -n "s/^$1=//p" .env | tr -d '\r'; }
PROJECT="$(get GCP_PROJECT_ID)"
REGION="${REGION:-asia-south1}"

# 1. Build the site. A production build calls its own origin (web/src/lib/data.ts), and
#    the Maps browser key from web/.env.local is compiled into the bundle.
npm --prefix web run build

# 2. Build the image from source and deploy. .gcloudignore decides what is uploaded;
#    it must keep web/dist in and every secret out.
gcloud run deploy vayusetu \
  --source . \
  --project "$PROJECT" --region "$REGION" \
  --allow-unauthenticated \
  --max-instances 2 --memory 1Gi --timeout 120 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT,GCP_REGION=$REGION,GEMINI_MODEL_FLASH=$(get GEMINI_MODEL_FLASH),GEMINI_MODEL_PRO=$(get GEMINI_MODEL_PRO)" \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
  --quiet

URL="$(gcloud run services describe vayusetu --project "$PROJECT" --region "$REGION" --format='value(status.url)')"

# 3. Smoke test the deployment, not the laptop.
code() { curl -s -o /dev/null -w '%{http_code}' "$1"; }
[ "$(code "$URL/health")" = 200 ] || { echo "health check failed"; exit 1; }
[ "$(code "$URL/")" = 200 ] || { echo "site not served"; exit 1; }
[ "$(code "$URL/api/v1/ncr/hotspots/top?limit=1")" = 200 ] || { echo "API cannot reach BigQuery"; exit 1; }
[ "$(code "$URL/.env")" = 404 ] || { echo ".env is reachable — stop and investigate"; exit 1; }
echo "Deployed and verified: $URL"
