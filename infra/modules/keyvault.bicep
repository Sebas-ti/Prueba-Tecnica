// Key Vault (RBAC) para secretos de la aplicación: API keys de clientes y cadena de App Insights.
param name string
param location string
param tags object
param principalId string
@secure()
param apiKeys string
@secure()
param appInsightsConnectionString string

var secretsUser = '4633458b-17de-408a-b874-0445c86b69e6' // Key Vault Secrets User

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('kv-${replace(name, '-', '')}', 24)
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled' // Producción: private endpoint
  }
}

resource apiKeysSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'api-keys'
  properties: { value: apiKeys }
}

resource aiSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'appinsights-connection-string'
  properties: { value: appInsightsConnectionString }
}

resource role 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, principalId, secretsUser)
  scope: kv
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUser)
  }
}

output name string = kv.name
output apiKeysSecretUri string = apiKeysSecret.properties.secretUri
output appInsightsSecretUri string = aiSecret.properties.secretUri
