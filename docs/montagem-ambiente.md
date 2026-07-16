# Montagem do ambiente experimental

Este guia descreve a preparação do ambiente Kubernetes e do Envoy AI Gateway
utilizado para executar os experimentos com GPT-4o-mini, Gemini-2.5-Flash e
DeepSeek-V4-Flash.

## Dependências

```sh

# Install kind
[ $(uname -m) = x86_64 ] && curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.32.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER && newgrp docker


# K9S
curl -sS https://webi.sh/k9s | sh;
cat << 'EOF' >> ~/.bashrc
if [ -f "$HOME/.config/envman/PATH.env" ]; then
  source "$HOME/.config/envman/PATH.env"
fi
EOF
source ~/.bashrc

# Install kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
chmod +x kubectl
mkdir -p ~/.local/bin
mv ./kubectl ~/.local/bin/kubectl

# Install Helm
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-4
chmod 700 get_helm.sh
./get_helm.sh
```

## Implantação do Envoy AI Gateway e dos modelos

```sh
kind create cluster --name istio-cluster --image kindest/node:v1.32.0

kubectl create ns envoy-gateway-system
kubectl apply -f manifests/redis.yaml
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.0.2/manifests.yaml
kubectl apply -f manifests/inferencepool-role.yaml

helm upgrade -i eg oci://docker.io/envoyproxy/gateway-helm \
--version v1.8.1 \
--namespace envoy-gateway-system \
--create-namespace \
-f https://raw.githubusercontent.com/envoyproxy/ai-gateway/main/manifests/envoy-gateway-values.yaml \
-f https://raw.githubusercontent.com/envoyproxy/ai-gateway/main/examples/token_ratelimit/envoy-gateway-values-addon.yaml \
-f https://raw.githubusercontent.com/envoyproxy/ai-gateway/main/examples/inference-pool/envoy-gateway-values-addon.yaml

helm upgrade -i aieg-crd oci://docker.io/envoyproxy/ai-gateway-crds-helm \
--version v1.0.0 \
--namespace envoy-ai-gateway-system \
--create-namespace

helm upgrade -i aieg oci://docker.io/envoyproxy/ai-gateway-helm \
--version v1.0.0 \
--namespace envoy-ai-gateway-system \
--create-namespace

helm upgrade -i aieg-crd oci://docker.io/envoyproxy/ai-gateway-crds-helm --version v1.0.0 --namespace envoy-ai-gateway-system --take-ownership
helm upgrade -i aieg oci://docker.io/envoyproxy/ai-gateway-helm --version v1.0.0 --namespace envoy-ai-gateway-system

kubectl apply -f https://raw.githubusercontent.com/envoyproxy/ai-gateway/main/examples/basic/basic.yaml

# Crie o arquivo .env a partir do exemplo e preencha as três chaves.
cp .env.example .env
set -a
source .env
set +a

# Renderiza as variáveis com envsubst e aplica OpenAI, Gemini e DeepSeek.
./scripts/apply-model-manifests.sh

export GATEWAY_URL="http://localhost:8080"

export ENVOY_SERVICE=$(kubectl get svc -n envoy-gateway-system \
--selector=gateway.envoyproxy.io/owning-gateway-namespace=default,gateway.envoyproxy.io/owning-gateway-name=envoy-ai-gateway-basic \
-o jsonpath='{.items[0].metadata.name}')

kubectl port-forward -n envoy-gateway-system svc/$ENVOY_SERVICE 8080:80 

curl -i -H "Content-Type: application/json" \
-H "x-ai-eg-model: gpt-4o-mini" \
-d '{ "model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Voce tem o reasoning atividado?."}] }' \
$GATEWAY_URL/v1/chat/completions

curl -i -H "Content-Type: application/json" \
-H "x-ai-eg-model: gemini-2.5-flash" \
-d '{ "model": "gemini-2.5-flash", "messages": [{"role": "user", "content": "voce é o gemini?."}] }' \
$GATEWAY_URL/v1/chat/completions

curl -i -H "Content-Type: application/json" \
-H "x-tenant-id: dev-team-1" \
-H "x-ai-eg-model: deepseek-v4-flash" \
-d '{
  "model": "deepseek-v4-flash",
  "messages": [
    {"role": "user", "content": "Voce tem o reasoning atividado?"}
  ]
}' $GATEWAY_URL/v1/chat/completions


git clone https://github.com/zhiqiangwang4/MCPTox-Benchmark.git
```
