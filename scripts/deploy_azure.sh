#!/usr/bin/env bash
# Despliegue de punta a punta en Azure.
#
# Requisitos: Azure CLI (az) con sesión iniciada (az login) y permisos de Owner o
# Contributor + User Access Administrator sobre el grupo de recursos (para RBAC).
#
# Uso:
#   export RAG_API_KEYS="$(openssl rand -hex 24)"
#   bash scripts/deploy_azure.sh <resource-group> [location]
set -euo pipefail

RG="${1:?Uso: deploy_azure.sh <resource-group> [location]}"
LOCATION="${2:-eastus2}"
: "${RAG_API_KEYS:?Defina RAG_API_KEYS (claves de cliente separadas por coma)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
# Da a su usuario acceso a OpenAI/Search/Cosmos (evaluación con LLM-juez, pruebas locales contra Azure)
export USER_PRINCIPAL_ID="${USER_PRINCIPAL_ID:-$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)}"

echo "==> 1/5 Grupo de recursos $RG en $LOCATION"
az group create -n "$RG" -l "$LOCATION" -o none

echo "==> 2/5 Plataforma (OpenAI, AI Search, Cosmos DB, Key Vault, ACR, monitoreo)"
DEPLOY_APP=false az deployment group create -g "$RG" -n platform \
  -f "$ROOT/infra/main.bicep" -p "$ROOT/infra/main.bicepparam" -o none
ACR=$(az deployment group show -g "$RG" -n platform --query properties.outputs.acrName.value -o tsv)
LOGIN_SERVER=$(az deployment group show -g "$RG" -n platform --query properties.outputs.acrLoginServer.value -o tsv)

echo "==> 3/5 Construcción de la imagen en ACR (sin Docker local)"
az acr build -r "$ACR" -t "rag-agent:$TAG" "$ROOT" -o none

echo "==> 4/5 Container Apps (API + Job de ingesta)"
# Las asignaciones de rol (AcrPull, Key Vault) pueden tardar unos minutos en propagarse:
# si el primer intento falla al descargar la imagen o leer secretos, se reintenta.
for attempt in 1 2 3; do
  if DEPLOY_APP=true APP_IMAGE="$LOGIN_SERVER/rag-agent:$TAG" az deployment group create -g "$RG" -n app \
      -f "$ROOT/infra/main.bicep" -p "$ROOT/infra/main.bicepparam" -o none; then
    break
  fi
  [ "$attempt" -eq 3 ] && { echo "El despliegue de Container Apps falló 3 veces"; exit 1; }
  echo "   Reintentando en 90 s (propagación de RBAC)..."; sleep 90
done
API_URL=$(az deployment group show -g "$RG" -n app --query properties.outputs.apiUrl.value -o tsv)
JOB=$(az deployment group show -g "$RG" -n app --query properties.outputs.ingestJobName.value -o tsv)

echo "==> 5/5 Ingesta inicial del corpus"
az containerapp job start -g "$RG" -n "$JOB" -o none

OUT() { az deployment group show -g "$RG" -n platform --query "properties.outputs.$1.value" -o tsv; }
echo
echo "Variables para su .env (modo Azure desde su equipo, autenticación con az login):"
echo "  LLM_PROVIDER=azure"
echo "  VECTOR_STORE_PROVIDER=azure_search"
echo "  HISTORY_PROVIDER=cosmos"
echo "  AZURE_OPENAI_ENDPOINT=$(OUT openAiEndpoint)"
echo "  AZURE_SEARCH_ENDPOINT=$(OUT searchEndpoint)"
echo "  COSMOS_ENDPOINT=$(OUT cosmosEndpoint)"
echo "  MIN_RELEVANCE_SCORE=0.40"
echo
echo "API desplegada: $API_URL"
echo "Documentación:  $API_URL/docs"
echo "Prueba rápida:"
echo "  curl -s -X POST $API_URL/v1/chat -H 'X-API-Key: <su clave>' -H 'Content-Type: application/json' \\"
echo "       -d '{\"question\": \"¿Cuál es el RTO de GESOL?\"}'"
echo "Evaluación contra Azure:"
echo "  python -m eval.run_eval --api-url $API_URL --api-key <su clave>"
