#!/usr/bin/env bash
# One-time (idempotent) setup of Accord on Google Cloud. Safe to re-run.
#
#   PROJECT_ID=accord-orvane-dc5b GITHUB_REPO=FairosMirza/accord \
#   DATABASE_URL_FILE=/path/to/db-url ./infra/gcp-setup.sh
#
# Creates:
#   - Artifact Registry repo for images
#   - Service accounts: accord-run (runtime, least privilege) and accord-deployer (CI/CD)
#   - Secrets: database URL, session secret, scheduler job token (never in code or env files)
#   - Private, versioned Cloud Storage bucket for quotes and invoices
#   - Workload Identity Federation so GitHub Actions deploys without long-lived keys
set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID}"
: "${GITHUB_REPO:?set GITHUB_REPO, e.g. org/accord}"
REGION="${REGION:-europe-west3}"
BUCKET="${BUCKET:-${PROJECT_ID}-attachments}"
RUN_SA="accord-run@${PROJECT_ID}.iam.gserviceaccount.com"
DEPLOY_SA="accord-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
g() { gcloud --project "$PROJECT_ID" --quiet "$@"; }
exists() { "$@" >/dev/null 2>&1; }

echo "==> APIs"
g services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com storage.googleapis.com

echo "==> Artifact Registry"
exists g artifacts repositories describe accord --location "$REGION" ||
  g artifacts repositories create accord --repository-format docker --location "$REGION" --description "Accord images"

echo "==> Service accounts"
exists g iam service-accounts describe "$RUN_SA" ||
  g iam service-accounts create accord-run --display-name "Accord runtime"
exists g iam service-accounts describe "$DEPLOY_SA" ||
  g iam service-accounts create accord-deployer --display-name "Accord CI/CD deployer"

echo "==> Secrets"
put_secret() {
  local name="$1" value="$2"
  exists g secrets describe "$name" || g secrets create "$name" --replication-policy automatic
  printf '%s' "$value" | g secrets versions add "$name" --data-file=- >/dev/null
  g secrets add-iam-policy-binding "$name" --member "serviceAccount:${RUN_SA}" --role roles/secretmanager.secretAccessor >/dev/null
}
if [[ -n "${DATABASE_URL_FILE:-}" ]]; then put_secret accord-database-url "$(cat "$DATABASE_URL_FILE")"; fi
exists g secrets describe accord-session-secret || put_secret accord-session-secret "$(openssl rand -base64 48)"
exists g secrets describe accord-job-token || put_secret accord-job-token "$(openssl rand -hex 32)"

echo "==> Attachment bucket (private, versioned)"
exists gcloud storage buckets describe "gs://${BUCKET}" ||
  g storage buckets create "gs://${BUCKET}" --location "$REGION" --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "gs://${BUCKET}" --versioning >/dev/null
# The app can add and read documents but never delete or overwrite them.
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member "serviceAccount:${RUN_SA}" --role roles/storage.objectCreator >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member "serviceAccount:${RUN_SA}" --role roles/storage.objectViewer >/dev/null

echo "==> Deployer permissions"
g projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${DEPLOY_SA}" --role roles/run.admin --condition None >/dev/null
g artifacts repositories add-iam-policy-binding accord --location "$REGION" --member "serviceAccount:${DEPLOY_SA}" --role roles/artifactregistry.writer >/dev/null
g iam service-accounts add-iam-policy-binding "$RUN_SA" --member "serviceAccount:${DEPLOY_SA}" --role roles/iam.serviceAccountUser >/dev/null

echo "==> Workload Identity Federation for GitHub Actions (${GITHUB_REPO})"
exists g iam workload-identity-pools describe github --location global ||
  g iam workload-identity-pools create github --location global --display-name "GitHub Actions"
exists g iam workload-identity-pools providers describe github-actions --location global --workload-identity-pool github ||
  g iam workload-identity-pools providers create-oidc github-actions --location global --workload-identity-pool github \
    --display-name "GitHub Actions" --issuer-uri "https://token.actions.githubusercontent.com" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition "assertion.repository == '${GITHUB_REPO}'"
g iam service-accounts add-iam-policy-binding "$DEPLOY_SA" --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${GITHUB_REPO}" >/dev/null

echo
echo "Done. GitHub repository variables to set:"
echo "  GCP_PROJECT_ID=${PROJECT_ID}"
echo "  GCP_REGION=${REGION}"
echo "  GCP_WIF_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github-actions"
echo "  GCP_DEPLOY_SA=${DEPLOY_SA}"
