#!/bin/bash
# ── Seed Vault ────────────────────────────────────────────────────────────────
# Pushes initial provider API keys into Infisical.
# Run this once after Infisical is bootstrapped and a machine token is created.
#
# Usage:
#   INFISICAL_MACHINE_TOKEN=<token> \
#   INFISICAL_PROJECT_ID=<project-id> \
#   OPENAI_API_KEY=sk-... \
#   ANTHROPIC_API_KEY=sk-ant-... \
#   GEMINI_API_KEY=AIza... \
#   GROQ_API_KEY=gsk_... \
#   bash scripts/seed-vault.sh

set -euo pipefail

if [ -f .env ]; then
  source .env
fi

INFISICAL_URL="${INFISICAL_URL:-http://localhost:8080}"
INFISICAL_PROJECT_ID="${INFISICAL_PROJECT_ID:-}"
INFISICAL_MACHINE_TOKEN="${INFISICAL_MACHINE_TOKEN:-}"
ENVIRONMENT="${ENVIRONMENT:-dev}"

log()       { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }
log_error() { echo "[ERROR] $1" >&2; }

push_secret() {
  local secret_name="$1"
  local secret_value="$2"
  local url="${INFISICAL_URL}/api/v3/secrets/raw/${secret_name}"

  log "Pushing secret: ${secret_name}"

  local response
  response=$(curl -s -w "\n%{http_code}" -X POST "$url" \
    -H "Authorization: Bearer ${INFISICAL_MACHINE_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"value\": \"$(echo "$secret_value" | sed 's/\\/\\\\/g; s/"/\\"/g')\"}" 2>/dev/null) || {
    log_error "Failed to push ${secret_name}"
    return 1
  }

  local http_code
  http_code=$(echo "$response" | tail -n1)

  if [ "$http_code" -eq 200 ] || [ "$http_code" -eq 201 ]; then
    log "OK: ${secret_name}"
    return 0
  else
    log_error "Failed: ${secret_name} — HTTP ${http_code}"
    return 1
  fi
}

main() {
  if [ -z "${INFISICAL_MACHINE_TOKEN:-}" ]; then
    log_error "INFISICAL_MACHINE_TOKEN is required"
    exit 1
  fi

  if [ -z "${INFISICAL_PROJECT_ID:-}" ]; then
    log_error "INFISICAL_PROJECT_ID is required"
    exit 1
  fi

  local secrets=("ANTHROPIC_API_KEY" "OPENAI_API_KEY" "GEMINI_API_KEY" "GROQ_API_KEY" "LITELLM_MASTER_KEY" "MISTRAL_API_KEY" "COHERE_API_KEY" "TOGETHER_API_KEY")
  local failed=0

  for secret_name in "${secrets[@]}"; do
    local value="${!secret_name:-}"
    if [ -n "$value" ]; then
      if ! push_secret "$secret_name" "$value"; then
        ((failed++)) || true
      fi
    else
      log "Skipping ${secret_name} — not set"
    fi
  done

  if [ $failed -gt 0 ]; then
    log_error "Failed to push ${failed} secret(s)"
    exit 1
  fi

  log "Done — all secrets pushed."
}

main "$@"
