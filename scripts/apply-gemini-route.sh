#!/usr/bin/env bash
# Renderiza manifests/routes/gemini_template.yaml com as variáveis do .env e aplica a rota.
#
# Variáveis (.env):
#   GEMINI_API_KEY                obrigatória
#   GEMINI_MODEL                  opcional, padrão gemini-2.5-flash
#   RATE_LIMIT_REQUESTS_PER_HOUR  opcional, padrão 2000
#
# A chave NÃO entra no manifesto: o Secret é criado/atualizado direto por este
# script (kubectl create secret ... | kubectl apply).
# O manifesto gerado fica em manifests/rendered/gemini.yaml (não versionado).
# Use --render-only para gerar o arquivo sem aplicar.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
[[ -f "${repo_root}/.env" ]] && source "${repo_root}/.env"
set +a

: "${GEMINI_API_KEY:?Set GEMINI_API_KEY in .env}"
export GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}"
export RATE_LIMIT_REQUESTS_PER_HOUR="${RATE_LIMIT_REQUESTS_PER_HOUR:-2000}"

command -v envsubst >/dev/null || { echo "envsubst is required (gettext)." >&2; exit 1; }

mkdir -p "${repo_root}/manifests/rendered"
out="${repo_root}/manifests/rendered/gemini.yaml"
(envsubst '${GEMINI_MODEL} ${RATE_LIMIT_REQUESTS_PER_HOUR}' \
  < "${repo_root}/manifests/routes/gemini_template.yaml" > "$out")
echo "Rendered: manifests/rendered/gemini.yaml"

if [[ "${1:-}" != "--render-only" ]]; then
  # A chave é passada por process substitution para não aparecer em argv.
  kubectl create secret generic "envoy-ai-gateway-basic-gemini-apikey" --namespace default \
    --from-file=apiKey=<(printf '%s' "$GEMINI_API_KEY") \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -f "$out"
fi
