#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for variable in OPENAI_API_KEY GEMINI_API_KEY DEEPSEEK_API_KEY; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Required environment variable is not set: ${variable}" >&2
    exit 1
  fi
done

if ! command -v envsubst >/dev/null 2>&1; then
  echo "envsubst is required (package: gettext or gettext-base)." >&2
  exit 1
fi

rendered_dir="$(mktemp -d)"
trap 'rm -rf "$rendered_dir"' EXIT

envsubst '${OPENAI_API_KEY}' \
  < "${repo_root}/manifests/openai.yaml" \
  > "${rendered_dir}/openai.yaml"
envsubst '${GEMINI_API_KEY}' \
  < "${repo_root}/manifests/gemini.yaml" \
  > "${rendered_dir}/gemini.yaml"
envsubst '${DEEPSEEK_API_KEY}' \
  < "${repo_root}/manifests/deepseek.yaml" \
  > "${rendered_dir}/deepseek.yaml"

kubectl apply -f "${rendered_dir}/openai.yaml"
kubectl apply -f "${rendered_dir}/gemini.yaml"
kubectl apply -f "${rendered_dir}/deepseek.yaml"

