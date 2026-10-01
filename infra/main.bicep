// Infraestructura del Agente RAG empresarial sobre Azure.
// Despliegue en dos fases (ver scripts/deploy_azure.sh):
//   1) deployApp=false -> plataforma (OpenAI, AI Search, Cosmos, Key Vault, ACR, monitoreo)
//   2) az acr build    -> imagen de la API
//   3) deployApp=true  -> Container Apps (API + Job de ingesta) con la imagen construida
targetScope = 'resourceGroup'

@description('Prefijo corto para nombrar recursos (minúsculas, sin espacios).')
@minLength(3)
@maxLength(10) // los nombres de Container Apps admiten máx. 32 caracteres
param prefix string = 'ic7rag'

@description('Ambiente lógico.')
@allowed([ 'dev', 'prod' ])
param environmentName string = 'dev'

param location string = resourceGroup().location

@description('Región para Azure OpenAI (disponibilidad de modelos).')
param openAiLocation string = location

@description('Modelo de chat y versión (verifique disponibilidad en la región y cuota).')
param chatModel string = 'gpt-5-mini'
param chatModelVersion string = '2025-08-07'

@description('API keys de clientes, separadas por coma. Se guardan en Key Vault.')
@secure()
param apiKeys string

@description('Opcional: objectId de su usuario (az ad signed-in-user show --query id -o tsv).')
param userPrincipalId string = ''

param deployApp bool = false
param image string = ''

var name = '${prefix}-${environmentName}-${take(uniqueString(resourceGroup().id), 5)}'
var tags = { app: 'enterprise-rag-agent', env: environmentName, owner: 'ic7', 'managed-by': 'bicep' }

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${name}'
  location: location
  tags: tags
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: { name: name, location: location, tags: tags }
}

module openai 'modules/openai.bicep' = {
  name: 'openai'
  params: {
    name: name
    location: openAiLocation
    tags: tags
    principalId: identity.properties.principalId
    chatModel: chatModel
    chatModelVersion: chatModelVersion
    userPrincipalId: userPrincipalId
  }
}

module search 'modules/search.bicep' = {
  name: 'search'
  params: { name: name, location: location, tags: tags, principalId: identity.properties.principalId, userPrincipalId: userPrincipalId }
}

module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos'
  params: { name: name, location: location, tags: tags, principalId: identity.properties.principalId, userPrincipalId: userPrincipalId }
}

module keyvault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    name: name
    location: location
    tags: tags
    principalId: identity.properties.principalId
    apiKeys: apiKeys
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
  }
}

module acr 'modules/acr.bicep' = {
  name: 'acr'
  params: { name: name, location: location, tags: tags, principalId: identity.properties.principalId }
}

module apps 'modules/containerapps.bicep' = if (deployApp) {
  name: 'containerapps'
  params: {
    name: name
    location: location
    tags: tags
    identityId: identity.id
    identityClientId: identity.properties.clientId
    logAnalyticsName: monitoring.outputs.logAnalyticsName
    acrLoginServer: acr.outputs.loginServer
    image: image
    apiKeysSecretUri: keyvault.outputs.apiKeysSecretUri
    appInsightsSecretUri: keyvault.outputs.appInsightsSecretUri
    openAiEndpoint: openai.outputs.endpoint
    chatDeployment: openai.outputs.chatDeployment
    embeddingDeployment: openai.outputs.embeddingDeployment
    searchEndpoint: search.outputs.endpoint
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabase: cosmos.outputs.databaseName
    cosmosContainer: cosmos.outputs.containerName
    environmentName: environmentName
  }
}

output acrName string = acr.outputs.name
output acrLoginServer string = acr.outputs.loginServer
output openAiEndpoint string = openai.outputs.endpoint
output searchEndpoint string = search.outputs.endpoint
output cosmosEndpoint string = cosmos.outputs.endpoint
output keyVaultName string = keyvault.outputs.name
output apiUrl string = deployApp ? apps!.outputs.apiUrl : ''
output apiName string = deployApp ? apps!.outputs.apiName : ''
output ingestJobName string = deployApp ? apps!.outputs.jobName : ''
