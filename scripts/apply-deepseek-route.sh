#!/usr/bin/env bash
# Renderiza manifests/routes/deepseek_template.yaml com as variáveis do .env e aplica a rota.
#
# Variáveis (.env):
#   DEEPSEEK_API_KEY              obrigatória
#   DEEPSEEK_MODEL                opcional, padrão deepseek-v4-flash
#   DEEPSEEK_MODEL_ALT            opcional, padrão deepseek-chat (segundo modelo
#                                 aceito pela mesma rota)
#   RATE_LIMIT_REQUESTS_PER_HOUR  opcional, padrão 2000
#
# A chave NÃO entra no manifesto: o Secret é criado/atualizado direto por este
# script (kubectl create secret ... | kubectl apply).
# O manifesto gerado fica em manifests/rendered/deepseek.yaml (não versionado).
# Use --render-only para gerar o arquivo sem aplicar.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
[[ -f "${repo_root}/.env" ]] && source "${repo_root}/.env"
set +a

: "${DEEPSEEK_API_KEY:?Set DEEPSEEK_API_KEY in .env}"
export DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-flash}"
export DEEPSEEK_MODEL_ALT="${DEEPSEEK_MODEL_ALT:-deepseek-chat}"
export RATE_LIMIT_REQUESTS_PER_HOUR="${RATE_LIMIT_REQUESTS_PER_HOUR:-2000}"

command -v envsubst >/dev/null || { echo "envsubst is required (gettext)." >&2; exit 1; }

mkdir -p "${repo_root}/manifests/rendered"
out="${repo_root}/manifests/rendered/deepseek.yaml"
(envsubst '${DEEPSEEK_MODEL} ${DEEPSEEK_MODEL_ALT} ${RATE_LIMIT_REQUESTS_PER_HOUR}' \
  < "${repo_root}/manifests/routes/deepseek_template.yaml" > "$out")
echo "Rendered: manifests/rendered/deepseek.yaml"

if [[ "${1:-}" != "--render-only" ]]; then
  # A chave é passada por process substitution para não aparecer em argv.
  kubectl create secret generic "envoy-ai-gateway-basic-deepseek-apikey" --namespace default \
    --from-file=apiKey=<(printf '%s' "$DEEPSEEK_API_KEY") \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -f "$out"
fi
