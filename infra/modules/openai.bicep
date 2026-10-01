// Azure OpenAI: modelo de chat + modelo de embeddings. Sin claves locales (solo Entra ID).
param name string
param location string
param tags object
param principalId string
param chatModel string = 'gpt-4o-mini'
param chatModelVersion string = '2024-07-18'
param chatCapacity int = 30
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

output endpoint string = openai.properties.endpoint
output chatDeployment string = chat.name
output embeddingDeployment string = embeddings.name
