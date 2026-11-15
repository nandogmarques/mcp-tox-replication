#!/usr/bin/env bash
# Renderiza manifests/routes/azure-openai_template.yaml com as variáveis do .env e aplica
# a rota Azure OpenAI / Microsoft Foundry de UM deployment. Para vários
# deployments, rode de novo com outro AZURE_MODEL (ou AZURE_ROUTE): cada rota
# tem recursos com nome próprio e elas coexistem no mesmo Gateway.
#
# Variáveis (.env):
#   AZURE_MODEL           obrigatória: nome do deployment (ex.: gpt-5-mini)
#   AZURE_ENDPOINT_HOST   obrigatória: host do recurso (ex.: meu-recurso.openai.azure.com)
#   AZURE_OPENAI_API_KEY  obrigatória
#   AZURE_API_VERSION     opcional, padrão 2025-03-01-preview
#   AZURE_ROUTE           opcional: sufixo dos recursos; padrão AZURE_MODEL em
#                         minúsculas, com [^a-z0-9-] trocado por '-'
#
# A chave NÃO entra no manifesto: o Secret é criado/atualizado direto por este
# script (kubectl create secret ... | kubectl apply).
# O manifesto gerado fica em manifests/rendered/azure-openai-<rota>.yaml (não
# versionado). Use --render-only para gerar o arquivo sem aplicar.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
[[ -f "${repo_root}/.env" ]] && source "${repo_root}/.env"
set +a

: "${AZURE_MODEL:?Set AZURE_MODEL in .env}"
: "${AZURE_ENDPOINT_HOST:?Set AZURE_ENDPOINT_HOST in .env}"
: "${AZURE_OPENAI_API_KEY:?Set AZURE_OPENAI_API_KEY in .env}"
export AZURE_API_VERSION="${AZURE_API_VERSION:-2025-03-01-preview}"
export AZURE_ROUTE="${AZURE_ROUTE:-$(echo "$AZURE_MODEL" | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//')}"
[[ -n "$AZURE_ROUTE" ]] || { echo "AZURE_MODEL gives an empty name; set AZURE_ROUTE." >&2; exit 1; }

command -v envsubst >/dev/null || { echo "envsubst is required (gettext)." >&2; exit 1; }

mkdir -p "${repo_root}/manifests/rendered"
out="${repo_root}/manifests/rendered/azure-openai-${AZURE_ROUTE}.yaml"
(envsubst '${AZURE_MODEL} ${AZURE_ENDPOINT_HOST} ${AZURE_API_VERSION} ${AZURE_ROUTE}' \
  < "${repo_root}/manifests/routes/azure-openai_template.yaml" > "$out")
echo "Rendered: manifests/rendered/azure-openai-${AZURE_ROUTE}.yaml"

if [[ "${1:-}" != "--render-only" ]]; then
  # A chave é passada por process substitution para não aparecer em argv.
  kubectl create secret generic "envoy-ai-gateway-basic-azure-openai-${AZURE_ROUTE}-apikey" --namespace default \
    --from-file=apiKey=<(printf '%s' "$AZURE_OPENAI_API_KEY") \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -f "$out"
fi
