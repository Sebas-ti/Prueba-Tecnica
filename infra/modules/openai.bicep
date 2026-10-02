// Azure OpenAI: modelo de chat + modelo de embeddings. Sin claves locales (solo Entra ID).
param name string
param location string
param tags object
param principalId string
@description('Opcional: objectId del desarrollador (Entra ID) para acceso desde su equipo.')
param userPrincipalId string = ''
// gpt-4o-mini está en estado Deprecated: las suscripciones nuevas ya no pueden desplegarlo.
param chatModel string = 'gpt-5-mini'
param chatModelVersion string = '2025-08-07'
// 30K TPM daba ~3-5 preguntas/min y producía 502 reales bajo carga moderada
// (ver docs/evidencias/azure/operacion.md); la cuota de la suscripción permite mucho más.
param chatCapacity int = 150
param embeddingModel string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'
param embeddingCapacity int = 30

var openAiUserRole = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // Cognitive Services OpenAI User

resource openai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'oai-${name}'
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'oai-${name}'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled' // Producción: 'Disabled' + private endpoint
  }
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: chatModel
  sku: { name: 'GlobalStandard', capacity: chatCapacity }
  properties: {
    model: { format: 'OpenAI', name: chatModel, version: chatModelVersion }
    raiPolicyName: 'Microsoft.DefaultV2' // filtros de contenido + detección de jailbreak
  }
}

resource embeddings 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: embeddingModel
  sku: { name: 'Standard', capacity: embeddingCapacity }
  properties: {
    model: { format: 'OpenAI', name: embeddingModel, version: embeddingModelVersion }
  }
  dependsOn: [ chat ] // los deployments de una cuenta no admiten creación en paralelo
}

resource roleUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openai.id, principalId, openAiUserRole)
  scope: openai
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRole)
  }
}

resource roleDev 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  name: guid(openai.id, userPrincipalId, openAiUserRole)
  scope: openai
  properties: {
    principalId: userPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRole)
  }
}

output endpoint string = openai.properties.endpoint
output chatDeployment string = chat.name
output embeddingDeployment string = embeddings.name
