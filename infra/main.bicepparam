using './main.bicep'

param prefix = 'ic7rag'
param environmentName = 'dev'
// Región con disponibilidad de gpt-4o-mini (GlobalStandard) y text-embedding-3-small
param openAiLocation = 'eastus2'
// Nunca versionar claves: se leen de una variable de entorno en el momento del despliegue
param apiKeys = readEnvironmentVariable('RAG_API_KEYS')
param deployApp = bool(readEnvironmentVariable('DEPLOY_APP', 'false'))
param image = readEnvironmentVariable('APP_IMAGE', '')
