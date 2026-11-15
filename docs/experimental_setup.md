# Experimental Setup

This guide describes the experimental setup of the Kubernetes and Envoy AI Gateway environment used to run the MCPTox experiments on models such as GPT-4o-mini, Gemini-2.5-Flash, DeepSeek-V4-Flash, etc.

## Install Dependencies

```sh
# Install kind
[ $(uname -m) = x86_64 ] && curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.32.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER && newgrp docker

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

## Deployment of Envoy AI Gateway and Models

All remote files use the same pinned version (`v1.0.0`). Using `main` mixes the controller version with newer values and examples, causing mismatches.

```sh
export EG_VERSION=v1.8.1
export AIGW_VERSION=v1.0.0
export AIGW_REF=v1.0.0   # envoyproxy/ai-gateway repository ref
AIGW_RAW=[https://raw.githubusercontent.com/envoyproxy/ai-gateway/$](https://raw.githubusercontent.com/envoyproxy/ai-gateway/$){AIGW_REF}
WAIT=5m

kind create cluster --name mcptox-cluster --image kindest/node:v1.32.0

# Redis (token rate limit backend)
kubectl apply -f manifests/redis.yaml
kubectl rollout status -n redis-system deployment/redis --timeout=${WAIT}

# Envoy Gateway (base values + token_ratelimit)
helm upgrade -i eg oci://docker.io/envoyproxy/gateway-helm \
--version ${EG_VERSION} \
--namespace envoy-gateway-system \
--create-namespace \
-f ${AIGW_RAW}/manifests/envoy-gateway-values.yaml \
-f ${AIGW_RAW}/examples/token_ratelimit/envoy-gateway-values-addon.yaml
kubectl wait --timeout=${WAIT} -n envoy-gateway-system deployment/envoy-gateway --for=condition=Available
kubectl wait --timeout=${WAIT} -n envoy-gateway-system deployment/envoy-ratelimit --for=condition=Available

# Envoy AI Gateway (CRDs and controller)
helm upgrade -i aieg-crd oci://docker.io/envoyproxy/ai-gateway-crds-helm \
--version ${AIGW_VERSION} \
--namespace envoy-ai-gateway-system \
--create-namespace

helm upgrade -i aieg oci://docker.io/envoyproxy/ai-gateway-helm \
--version ${AIGW_VERSION} \
--namespace envoy-ai-gateway-system \
--create-namespace
kubectl wait --timeout=${WAIT} -n envoy-ai-gateway-system deployment/ai-gateway-controller --for=condition=Available

kubectl apply -f ${AIGW_RAW}/examples/basic/basic.yaml
```

The data-plane Service is created asynchronously after the `Gateway`.
Wait for the pod to exist and become ready before searching for the Service:

```sh
until kubectl get pod -n envoy-gateway-system \
  -l gateway.envoyproxy.io/owning-gateway-name=envoy-ai-gateway-basic \
  -o name 2>/dev/null | grep -q .; do sleep 2; done
kubectl wait --timeout=${WAIT} -n envoy-gateway-system pod \
  -l gateway.envoyproxy.io/owning-gateway-name=envoy-ai-gateway-basic \
  --for=condition=Ready
```

In kind, the `Gateway` status stays at `Programmed=False` (`AddressNotAssigned`), because
the `LoadBalancer` Service does not receive an address without an LB provider. This is
expected and does not prevent the `port-forward` below.

### Model Routes

Each of the following scripts deploys a route for the respective model. Ensure that the variables are properly defined in `.env`.

```sh
cp .env.example .env   # edit with the keys

./scripts/apply-openai-route.sh
./scripts/apply-gemini-route.sh
./scripts/apply-deepseek-route.sh
./scripts/apply-azure-route.sh
```

### Route Testing

```sh
export GATEWAY_URL="http://localhost:8080"

export ENVOY_SERVICE=$(kubectl get svc -n envoy-gateway-system --selector=gateway.envoyproxy.io/owning-gateway-namespace=default,gateway.envoyproxy.io/owning-gateway-name=envoy-ai-gateway-basic -o jsonpath='{.items[0].metadata.name}')

kubectl port-forward -n envoy-gateway-system svc/$ENVOY_SERVICE 8080:80 &

curl -i -H "Content-Type: application/json" \
-H "x-ai-eg-model: gpt-4o-mini" \
-d '{ "model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Do you have reasoning enabled?"}] }' \
$GATEWAY_URL/v1/chat/completions

curl -i -H "Content-Type: application/json" \
-H "x-ai-eg-model: gemini-2.5-flash" \
-d '{ "model": "gemini-2.5-flash", "messages": [{"role": "user", "content": "Are you Gemini?"}] }' \
$GATEWAY_URL/v1/chat/completions

curl -i -H "Content-Type: application/json" \
-H "x-tenant-id: dev-team-1" \
-H "x-ai-eg-model: deepseek-v4-flash" \
-d '{
  "model": "deepseek-v4-flash",
  "messages": [
    {"role": "user", "content": "Do you have reasoning enabled?"}
  ]
}' $GATEWAY_URL/v1/chat/completions

# Azure OpenAI / Microsoft Foundry: the model is the deployment name (AZURE_MODEL)
curl -i -H "Content-Type: application/json" \
-H "x-ai-eg-model: gpt-5-mini" \
-d '{ "model": "gpt-5-mini", "messages": [{"role": "user", "content": "Do you have reasoning enabled?"}] }' \
$GATEWAY_URL/v1/chat/completions
```

## Teardown

```sh
kind delete cluster --name mcptox-cluster
```