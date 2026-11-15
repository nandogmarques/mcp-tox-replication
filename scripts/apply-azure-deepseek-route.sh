#!/usr/bin/env bash
# Renderiza manifests/routes/azure-deepseek_template.yaml com as variáveis do
# .env e aplica a rota de UM deployment DeepSeek provido pelo Microsoft Foundry
# (Azure). Para vários deployments, rode de novo com outro FOUNDRY_DEEPSEEK_MODEL
# (ou FOUNDRY_DEEPSEEK_ROUTE): cada rota tem recursos com nome próprio e elas
# coexistem no mesmo Gateway, inclusive com a rota DeepSeek direta.
#
# Variáveis (.env):
#   FOUNDRY_DEEPSEEK_MODEL          obrigatória: nome do deployment no Foundry
#                                   (ex.: DeepSeek-V4-Flash). Deve ser diferente
#                                   dos modelos da rota DeepSeek direta.
#   FOUNDRY_DEEPSEEK_ENDPOINT_HOST  opcional, padrão AZURE_ENDPOINT_HOST: host
#                                   do recurso (ex.: meu-recurso.openai.azure.com)
#   FOUNDRY_DEEPSEEK_API_KEY        opcional, padrão AZURE_OPENAI_API_KEY: chave
#                                   do recurso
#   FOUNDRY_DEEPSEEK_API_VERSION    opcional, padrão 2025-03-01-preview
#   FOUNDRY_DEEPSEEK_ROUTE          opcional: sufixo dos recursos; padrão
#                                   FOUNDRY_DEEPSEEK_MODEL em minúsculas, com
#                                   [^a-z0-9-] trocado por '-'
#
# A chave NÃO entra no manifesto: o Secret é criado/atualizado direto por este
# script (kubectl create secret ... | kubectl apply).
# O manifesto gerado fica em manifests/rendered/azure-deepseek-<rota>.yaml (não
# versionado). Use --render-only para gerar o arquivo sem aplicar.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
[[ -f "${repo_root}/.env" ]] && source "${repo_root}/.env"
set +a

: "${FOUNDRY_DEEPSEEK_MODEL:?Set FOUNDRY_DEEPSEEK_MODEL in .env}"
export FOUNDRY_DEEPSEEK_ENDPOINT_HOST="${FOUNDRY_DEEPSEEK_ENDPOINT_HOST:-${AZURE_ENDPOINT_HOST:-}}"
FOUNDRY_DEEPSEEK_API_KEY="${FOUNDRY_DEEPSEEK_API_KEY:-${AZURE_OPENAI_API_KEY:-}}"
[[ -n "$FOUNDRY_DEEPSEEK_ENDPOINT_HOST" ]] || {
  echo "Set FOUNDRY_DEEPSEEK_ENDPOINT_HOST (or AZURE_ENDPOINT_HOST) in .env" >&2; exit 1; }
# Aceita uma URL colada do portal (ex.: https://x.services.ai.azure.com/api/projects/p)
# e mantém só o host, que é o que o Backend e o BackendTLSPolicy aceitam.
host="${FOUNDRY_DEEPSEEK_ENDPOINT_HOST#*://}"; host="${host%%/*}"; host="${host,,}"
if [[ "$host" != "$FOUNDRY_DEEPSEEK_ENDPOINT_HOST" ]]; then
  echo "NOTE: using host '$host' from FOUNDRY_DEEPSEEK_ENDPOINT_HOST='$FOUNDRY_DEEPSEEK_ENDPOINT_HOST'." >&2
fi
[[ "$host" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$ ]] || {
  echo "Invalid FOUNDRY_DEEPSEEK_ENDPOINT_HOST: '$host' (expected a hostname such as my-resource.openai.azure.com)." >&2; exit 1; }
export FOUNDRY_DEEPSEEK_ENDPOINT_HOST="$host"
[[ -n "$FOUNDRY_DEEPSEEK_API_KEY" ]] || {
  echo "Set FOUNDRY_DEEPSEEK_API_KEY (or AZURE_OPENAI_API_KEY) in .env" >&2; exit 1; }
export FOUNDRY_DEEPSEEK_API_VERSION="${FOUNDRY_DEEPSEEK_API_VERSION:-2025-03-01-preview}"
export FOUNDRY_DEEPSEEK_ROUTE="${FOUNDRY_DEEPSEEK_ROUTE:-$(echo "$FOUNDRY_DEEPSEEK_MODEL" \
  | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//')}"
[[ -n "$FOUNDRY_DEEPSEEK_ROUTE" ]] || {
  echo "FOUNDRY_DEEPSEEK_MODEL gives an empty name; set FOUNDRY_DEEPSEEK_ROUTE." >&2; exit 1; }

# O Gateway escolhe a rota pelo valor exato (com diferença de maiúsculas) do
# header x-ai-eg-model. Um nome idêntico ao da rota DeepSeek direta faria as
# duas rotas disputarem o mesmo modelo; um nome que só difere na caixa funciona,
# mas é fácil de confundir ao passar --model ao runner.
for direct in "${DEEPSEEK_MODEL:-deepseek-v4-flash}" "${DEEPSEEK_MODEL_ALT:-deepseek-chat}"; do
  if [[ "$FOUNDRY_DEEPSEEK_MODEL" == "$direct" ]]; then
    echo "FOUNDRY_DEEPSEEK_MODEL ('$FOUNDRY_DEEPSEEK_MODEL') is the same model name as the direct DeepSeek route; use another deployment name." >&2
    exit 1
  fi
  if [[ "${FOUNDRY_DEEPSEEK_MODEL,,}" == "${direct,,}" ]]; then
    echo "NOTE: '$FOUNDRY_DEEPSEEK_MODEL' (Foundry) and '$direct' (direct DeepSeek route) differ only in case; pass the exact name to --model." >&2
  fi
done

command -v envsubst >/dev/null || { echo "envsubst is required (gettext)." >&2; exit 1; }

mkdir -p "${repo_root}/manifests/rendered"
out="${repo_root}/manifests/rendered/azure-deepseek-${FOUNDRY_DEEPSEEK_ROUTE}.yaml"
(envsubst '${FOUNDRY_DEEPSEEK_MODEL} ${FOUNDRY_DEEPSEEK_ENDPOINT_HOST} ${FOUNDRY_DEEPSEEK_API_VERSION} ${FOUNDRY_DEEPSEEK_ROUTE}' \
  < "${repo_root}/manifests/routes/azure-deepseek_template.yaml" > "$out")
echo "Rendered: manifests/rendered/azure-deepseek-${FOUNDRY_DEEPSEEK_ROUTE}.yaml"

if [[ "${1:-}" != "--render-only" ]]; then
  # A chave é passada por process substitution para não aparecer em argv.
  kubectl create secret generic "envoy-ai-gateway-basic-azure-deepseek-${FOUNDRY_DEEPSEEK_ROUTE}-apikey" --namespace default \
    --from-file=apiKey=<(printf '%s' "$FOUNDRY_DEEPSEEK_API_KEY") \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -f "$out"
fi
