using './main.bicep'

param prefix = 'ic7rag'
param environmentName = 'dev'
// Región con disponibilidad de gpt-5-mini (GlobalStandard) y text-embedding-3-small
param openAiLocation = 'eastus2'
// Región separada para AI Search: la capacidad del SKU Basic varía por región/momento
param searchLocation = readEnvironmentVariable('SEARCH_LOCATION', 'eastus')
// Nunca versionar claves: se leen de una variable de entorno en el momento del despliegue
param apiKeys = readEnvironmentVariable('RAG_API_KEYS')
param deployApp = bool(readEnvironmentVariable('DEPLOY_APP', 'false'))
param image = readEnvironmentVariable('APP_IMAGE', '')
param chatModel = readEnvironmentVariable('CHAT_MODEL', 'gpt-5-mini')
param chatModelVersion = readEnvironmentVariable('CHAT_MODEL_VERSION', '2025-08-07')
// Acceso de su usuario a OpenAI/Search/Cosmos (para evaluación con LLM-juez y pruebas locales)
param userPrincipalId = readEnvironmentVariable('USER_PRINCIPAL_ID', '')
