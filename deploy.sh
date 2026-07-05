#!/usr/bin/env bash
# Deploy do Materlux no Cloud Run, com imagem marcada pelo commit do Git.
# Rode de DENTRO do repositório (ex.: no Cloud Shell, após `git pull`).
# Segredos ficam no Secret Manager — nenhum valor sensível aqui.
set -euo pipefail

PROJECT="mata-da-praia-workflows"
REGION="southamerica-east1"
INSTANCE="mata-da-praia-workflows:southamerica-east1:materlux-db"
SERVICE="materlux-api"
REPO="southamerica-east1-docker.pkg.dev/${PROJECT}/materlux/materlux-api"

# Tag = commit curto do Git (+ sufixo -dirty se houver mudança não commitada).
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
git diff --quiet 2>/dev/null || GIT_SHA="${GIT_SHA}-dirty"
IMG="${REPO}:${GIT_SHA}"
echo ">> Imagem: ${IMG}"

gcloud config set project "$PROJECT" >/dev/null

# --- Build + push da imagem ---------------------------------------------------
# O daemon do Docker no Cloud Shell não envia para o Artifact Registry (quirk de
# rede); por isso publicamos com o crane (userspace), que funciona.
if [ ! -x /tmp/crane ]; then
  echo ">> Baixando crane..."
  (cd /tmp && curl -sSL \
    https://github.com/google/go-containerregistry/releases/latest/download/go-containerregistry_Linux_x86_64.tar.gz \
    | tar xz crane)
fi
docker build -t "$IMG" .
docker save "$IMG" -o /tmp/materlux-img.tar
/tmp/crane push /tmp/materlux-img.tar "$IMG"

# --- Deploy no Cloud Run ------------------------------------------------------
gcloud run deploy "$SERVICE" \
  --image "$IMG" \
  --region "$REGION" \
  --allow-unauthenticated \
  --add-cloudsql-instances "$INSTANCE" \
  --set-secrets "DATABASE_URL=materlux-database-url:latest,JWT_SECRET=materlux-jwt-secret:latest,GEMINI_API_KEY=materlux-gemini-key:latest,ZAPI_INSTANCE=materlux-zapi-instance:latest,ZAPI_TOKEN=materlux-zapi-token:latest,ZAPI_CLIENT_TOKEN=materlux-zapi-client-token:latest" \
  --set-env-vars "WA_PROVIDER=zapi,WA_VERIFY_TOKEN=materlux-verify,CLINIC_TZ=America/Sao_Paulo,COOKIE_SECURE=true,GEMINI_MODEL=gemini-2.5-flash"

echo ""
echo ">> No ar. Revisao aponta para o commit ${GIT_SHA}."
gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'

# --- Rollback (referencia) ----------------------------------------------------
#   gcloud run revisions list --service materlux-api --region southamerica-east1
#   gcloud run services update-traffic materlux-api --region southamerica-east1 \
#       --to-revisions <REVISAO-ANTERIOR>=100
