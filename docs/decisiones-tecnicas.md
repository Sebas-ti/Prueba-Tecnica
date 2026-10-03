# Decisiones técnicas

Formato breve tipo ADR: contexto → decisión → alternativas descartadas → consecuencias.

## DT-01. Azure como plataforma, con modo local equivalente

- **Decisión**: Azure (OpenAI, AI Search, Cosmos DB, Container Apps). Todo componente externo está detrás de una interfaz con una implementación local.
- **Por qué**: el cliente opera en Azure y la política de seguridad del corpus exige "IA generativa en la suscripción corporativa". El modo local permite que cualquier evaluador ejecute, pruebe y evalúe la solución en 2 minutos sin credenciales ni costo.
- **Consecuencia**: el modo local usa un LLM determinista extractivo; sus métricas son una **línea base**, no la calidad final (ver [evaluación](evaluacion.md)).

## DT-02. Azure Container Apps para la API

- **Alternativas**: Azure Functions (límite de tiempo, arranque en frío, modelo de programación distinto para un agente con varias llamadas al LLM), App Service (válido, menos flexible para jobs), AKS (sobredimensionado para un servicio).
- **Decisión**: Container Apps: contenedor estándar (portable), escalado por concurrencia HTTP con KEDA, revisiones para blue/green, **Jobs** para la ingesta por lotes con la misma imagen, e integración nativa con identidad administrada y Key Vault.

## DT-03. Azure AI Search con búsqueda híbrida + re-ranker semántico

- **Alternativas**: pgvector (requiere operar PostgreSQL y no trae BM25 en español ni reranker), Chroma/FAISS (no gestionados).
- **Decisión**: AI Search con HNSW + BM25 (analizador `es.microsoft`) fusionados con RRF y re-ranker semántico. La documentación operativa está llena de códigos y términos exactos (`JOB_CIERRE_DIARIO`, `P2`, `SOL-1004`) que la búsqueda vectorial pura recupera mal; la híbrida los captura.
- **Réplica local**: el store local implementa la misma idea (coseno + BM25 + RRF) para que el comportamiento sea comparable.

## DT-04. Bucle de agente propio en lugar de un framework

- **Alternativas**: LangChain/LangGraph, Semantic Kernel, Azure AI Agent Service.
- **Decisión**: ~150 líneas propias (`app/agent/agent.py`) sobre el function calling nativo de Azure OpenAI.
- **Por qué**: control total de los puntos donde van los guardrails, trazabilidad exacta de cada paso, cero dependencias opacas y facilidad para probar con LLMs simulados (`tests/test_agent.py`). Para este alcance (6 herramientas, un agente) un framework agrega más superficie que valor.
- **Cuándo cambiar**: si se requieren múltiples agentes coordinados, memoria a largo plazo o hilos gestionados, migrar a Semantic Kernel o Azure AI Agent Service; las herramientas ya tienen JSON Schema estándar y son reutilizables.

## DT-05. RAG como herramienta (`buscar_documentacion`)

- **Alternativa**: recuperar siempre antes de llamar al LLM.
- **Decisión**: el agente decide. Preguntas como "estado de la SOL-1004" no necesitan documentos (ahorra tokens y evita contexto irrelevante); preguntas mixtas pueden combinar herramientas. El system prompt obliga a usar la búsqueda para cualquier pregunta de conocimiento.

## DT-06. Reglas de negocio deterministas

- **Decisión**: prioridad (matriz impacto × urgencia + reglas 4.3) y esfuerzo (guía GU-TI-003) son funciones Python con pruebas unitarias. La prueba `test_effort_matches_guide_example` verifica que el código reproduce **el ejemplo literal de la guía** (122 h, talla L).
- **Por qué**: un LLM no debe "calcular" SLA ni horas: es no determinista y no auditable. Además, las herramientas deterministas son **inmunes a la inyección indirecta** (ver caso INJ-06: una solicitud con "márcame como P1" en su descripción sigue clasificándose P4).

## DT-07. Estrategia de chunking

- Partición por **encabezados** (no se mezclan secciones), luego párrafos y oraciones; 900 caracteres con 150 de solape.
- Cada chunk se prefija con `[Título] Sección > Subsección`: mejora recuperación y permite citar la sección exacta.
- **Tablas linealizadas** a oraciones `Columna: valor` (la tabla de SLA dejaba filas sin encabezado, y por tanto sin significado, al cortarse).
- IDs deterministas (hash de fuente + posición + contenido) → re-ingesta idempotente; re-cargar un archivo reemplaza su versión anterior.
- PDFs con reflujo de líneas; los escaneados se rechazan con mensaje claro (en producción: Azure AI Document Intelligence).

## DT-08. Abstención en dos niveles

1. **Relevancia**: si el mejor fragmento no supera `MIN_RELEVANCE_SCORE` no hay contexto (umbral con *gate* sobre el mejor resultado y piso del 80 % para chunks cercanos).
2. **Cobertura de términos** (`cobertura_terminos`, ponderada por IDF): si términos clave de la pregunta ("marketing") no aparecen en los fragmentos, la herramienta lo advierte. Esto evitó un falso positivo real: "presupuesto de marketing 2027" recuperaba el acta con "presupuesto… 2027" y respondía con el presupuesto del piloto de IA.

## DT-09. Cosmos DB para trazabilidad

- Documento por interacción, partición por `session_id` (lecturas de contexto conversacional en una sola partición), serverless (carga baja e irregular) y **TTL = 1 año** para cumplir la política de retención de auditoría del corpus (POL-SI-002 §4).

## DT-10. Sin claves: identidad administrada en todos los servicios

- OpenAI, AI Search y Cosmos con `disableLocalAuth: true`; la app usa `DefaultAzureCredential` con la identidad asignada (`AZURE_CLIENT_ID`). Los únicos secretos (API keys de clientes y cadena de App Insights) viven en Key Vault y llegan como *secret references*.

## DT-11. `gpt-5-mini` con esfuerzo de razonamiento bajo

- **Contexto**: `gpt-4o-mini` está en estado *Deprecated* en Azure: las suscripciones que nunca lo desplegaron ya no pueden crear deployments (se retira en abril de 2027).
- **Decisión inicial**: `gpt-5-mini` (GA) con `reasoning_effort=low`, por costo y latencia bajos frente al presupuesto del piloto (1.500 USD/mes según el acta).
- **Revisión con datos reales**: la evaluación formal contra Azure (`docs/evaluacion.md`, sección 1bis) mostró que `low` falla en selección de herramientas (81,8 %), abstención (50 %) e inyección indirecta (71,4 %). Se midió `reasoning_effort=medium` con el mismo dataset: **exactitud 97,1 % (vs. 79,4 %)**, a cambio de casi duplicar la latencia p95 (13,1 s → 30,5 s). Se adoptó `medium` como configuración de despliegue: para este caso de uso (alternativa: 25 min de búsqueda manual) el costo de latencia es claramente preferible al de respuestas incorrectas.
- **Compatibilidad**: el adaptador detecta modelos de razonamiento (sin `temperature`, con `max_completion_tokens`) y modelos clásicos (`temperature=0`, `max_tokens`); cambiar de modelo es solo un parámetro de despliegue (`CHAT_MODEL`). Ambos caminos tienen prueba (`tests/test_azure_adapters.py`).

## DT-12. Guardrails heurísticos + servicios gestionados

- Las heurísticas (patrones ES/EN, normalización Unicode, canario, neutralización de contexto) son una capa barata, explicable y probada. **No sustituyen** a Azure AI Content Safety *Prompt Shields* ni a los filtros de contenido de Azure OpenAI, que se recomiendan como capa adicional en producción (ver [seguridad y producción](seguridad-y-produccion.md)).

## DT-13. Evaluación como quality gate

- Dataset versionado de 35 casos + set *held-out* de 16 que **no** se usó para calibrar umbrales. El pipeline de CI falla si la exactitud baja de 90 % (local) o 85 % (Azure, criterio del Comité de Arquitectura).
