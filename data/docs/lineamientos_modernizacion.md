# Lineamientos de Modernización de Aplicaciones Legadas

Documento del Comité de Arquitectura — Versión 1.2 — 2026

## 1. Principios

1. Modernización incremental: preferir el patrón strangler fig sobre reescrituras completas ("big bang").
2. API first: toda capacidad nueva debe exponerse mediante APIs REST documentadas con OpenAPI y publicadas en el API Gateway corporativo.
3. Servicios gestionados primero: preferir servicios PaaS y serverless sobre máquinas virtuales administradas por la organización.
4. Seguridad por diseño: identidades administradas, secretos en Key Vault, cifrado en tránsito y en reposo, y redes privadas.
5. Observabilidad desde el inicio: logs estructurados, trazas distribuidas y métricas de negocio.

## 2. Estrategias de migración (6R)

- Rehost: mover la aplicación sin cambios a máquinas virtuales en la nube. Útil como paso temporal.
- Replatform: cambios menores para usar servicios gestionados, por ejemplo mover la base de datos a un servicio administrado.
- Refactor: rediseñar la aplicación con arquitectura nativa de nube (contenedores, microservicios, serverless).
- Repurchase: reemplazar por un producto SaaS.
- Retire: retirar capacidades que ya no se usan.
- Retain: mantener temporalmente en el entorno actual.

Para GESOL el Comité de Arquitectura definió la estrategia Refactor incremental: primero una capa de APIs y un asistente inteligente de consulta sobre la documentación y las solicitudes; después, migrar módulo por módulo a contenedores.

## 3. Plataforma de referencia en Azure

- Cómputo de APIs y servicios: Azure Container Apps.
- Exposición y gobierno de APIs: Azure API Management.
- IA generativa: Azure OpenAI Service con acceso por red privada.
- Búsqueda y recuperación (RAG): Azure AI Search con búsqueda híbrida y semántica.
- Datos operacionales NoSQL: Azure Cosmos DB; datos relacionales: Azure Database for PostgreSQL o Azure SQL.
- Documentos y adjuntos: Azure Blob Storage con cifrado y ciclo de vida.
- Secretos: Azure Key Vault. Observabilidad: Azure Monitor y Application Insights.

## 4. Criterios de priorización de módulos

Se modernizan primero los módulos con mayor dolor para los usuarios y menor acoplamiento: consulta y búsqueda de solicitudes, reportes y notificaciones. El módulo de aprobaciones se modernizará al final por su dependencia con SAP HCM.
