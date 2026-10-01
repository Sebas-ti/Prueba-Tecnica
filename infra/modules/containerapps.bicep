// Azure Container Apps: entorno + API + Job de ingesta.
param name string
param location string
param tags object
param identityId string
param identityClientId string
param logAnalyticsName string
param acrLoginServer string
param image string
param apiKeysSecretUri string
param appInsightsSecretUri string
param openAiEndpoint string
param chatDeployment string
param embeddingDeployment string
param searchEndpoint string
param cosmosEndpoint string
param cosmosDatabase string
param cosmosContainer string
param environmentName string = 'dev'
param minReplicas int = 1
param maxReplicas int = 5

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${name}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var commonEnv = [
  { name: 'ENVIRONMENT', value: environmentName }
  { name: 'LOG_LEVEL', value: 'INFO' }
  { name: 'LLM_PROVIDER', value: 'azure' }
  { name: 'VECTOR_STORE_PROVIDER', value: 'azure_search' }
  { name: 'HISTORY_PROVIDER', value: 'cosmos' }
  { name: 'AZURE_CLIENT_ID', value: identityClientId } // DefaultAzureCredential -> identidad administrada
  { name: 'AZURE_OPENAI_ENDPOINT', value: openAiEndpoint }
  { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chatDeployment }
  { name: 'AZURE_OPENAI_API_VERSION', value: '2025-04-01-preview' }
  // low daba 79,4% de exactitud en la evaluación formal (docs/evaluacion.md, 1ter);
  // medium sube a 97,1% a cambio de ~2x la latencia p95 — tradeoff aceptado.
  { name: 'REASONING_EFFORT', value: 'medium' }
  { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: embeddingDeployment }
  { name: 'AZURE_SEARCH_ENDPOINT', value: searchEndpoint }
  { name: 'AZURE_SEARCH_INDEX', value: 'ic7-knowledge' }
  { name: 'MIN_RELEVANCE_SCORE', value: '0.4' } // reranker semántico normalizado (1.6 / 4)
  { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
  { name: 'COSMOS_DATABASE', value: cosmosDatabase }
  { name: 'COSMOS_CONTAINER', value: cosmosContainer }
  { name: 'API_KEYS', secretRef: 'api-keys' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights' }
]

var secrets = [
  { name: 'api-keys', keyVaultUrl: apiKeysSecretUri, identity: identityId }
  { name: 'appinsights', keyVaultUrl: appInsightsSecretUri, identity: identityId }
]

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${name}-api'
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true // Producción: interno + Azure API Management delante
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [ { server: acrLoginServer, identity: identityId } ]
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: commonEnv
          probes: [
            { type: 'Liveness', httpGet: { path: '/health', port: 8000 }, periodSeconds: 30 }
            { type: 'Readiness', httpGet: { path: '/ready', port: 8000 }, initialDelaySeconds: 10, periodSeconds: 15 }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [ { name: 'http', http: { metadata: { concurrentRequests: '20' } } } ]
      }
    }
  }
}

// Job manual para (re)indexar el corpus base: az containerapp job start
resource ingestJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'caj-${name}-ingest'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 1
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [ { server: acrLoginServer, identity: identityId } ]
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'ingest'
          image: image
          command: [ 'python', '-m', 'scripts.ingest' ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: commonEnv
        }
      ]
    }
  }
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output apiName string = api.name
output jobName string = ingestJob.name
