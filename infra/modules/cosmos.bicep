// Cosmos DB (NoSQL, serverless) para historial / trazabilidad de interacciones.
param name string
param location string
param tags object
param principalId string
param databaseName string = 'ragagent'
param containerName string = 'interactions'
@description('Retención de interacciones en segundos (política: 1 año).')
param ttlSeconds int = 31536000

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: 'cosmos-${name}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [ { locationName: location, failoverPriority: 0 } ]
    capabilities: [ { name: 'EnableServerless' } ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    disableLocalAuth: true // solo Entra ID
    minimalTlsVersion: 'Tls12'
  }
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: account
  name: databaseName
  properties: { resource: { id: databaseName } }
}

resource container 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: db
  name: containerName
  properties: {
    resource: {
      id: containerName
      partitionKey: { paths: [ '/session_id' ], kind: 'Hash' }
      defaultTtl: ttlSeconds
    }
  }
}

// Rol de plano de datos: Cosmos DB Built-in Data Contributor
resource dataRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: account
  name: guid(account.id, principalId, 'data-contributor')
  properties: {
    principalId: principalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    scope: account.id
  }
}

output endpoint string = account.properties.documentEndpoint
output databaseName string = databaseName
output containerName string = containerName
