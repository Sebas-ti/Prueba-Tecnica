// Azure AI Search con ranker semántico. Solo autenticación Entra ID (RBAC).
param name string
param location string
param tags object
param principalId string
@allowed([ 'basic', 'standard' ])
param sku string = 'basic'

var indexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // Search Index Data Contributor
var serviceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // Search Service Contributor (crear índices)

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: 'srch-${name}'
  location: location
  tags: tags
  sku: { name: sku }
  properties: {
    replicaCount: 1
    partitionCount: 1
    semanticSearch: 'free'
    disableLocalAuth: true
    publicNetworkAccess: 'enabled' // Producción: 'disabled' + private endpoint
  }
}

resource dataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, principalId, indexDataContributor)
  scope: search
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', indexDataContributor)
  }
}

resource serviceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, principalId, serviceContributor)
  scope: search
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceContributor)
  }
}

output endpoint string = 'https://${search.name}.search.windows.net'
