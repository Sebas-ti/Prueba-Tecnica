# Seguridad, operación y consideraciones para producción

## 1. Controles implementados

| Requisito (5.5) | Implementación | Dónde |
| --- | --- | --- |
| Variables de entorno | Configuración tipada con `pydantic-settings`; validación de combinaciones inválidas al arrancar (p. ej. `dev/prod` sin `API_KEYS` no arranca) | `app/config.py` |
| Separación de secretos | `SecretStr` (nunca se imprimen); `.env` fuera de git; en Azure: Key Vault + identidad administrada, `disableLocalAuth` en OpenAI, AI Search y Cosmos | `app/config.py`, `infra/` |
| Logging básico | JSON estructurado con `request_id` propagado (cabecera `X-Request-ID`), eventos de negocio (`agent_interaction`, `tool_executed`, `retrieval`, `prompt_injection_blocked`…) y **redacción de PII** (correos, teléfonos, tarjetas, claves) | `app/core/logging.py` |
| Validación de entradas | Pydantic (longitudes, patrones de `session_id`, enumeraciones), saneamiento de caracteres de control y de ancho cero, validación de archivos (extensión, tamaño, firma mágica, nombre seguro, máx. 20 por petición) | `app/api/`, `app/core/security.py` |
| Manejo de errores | Jerarquía de errores de dominio → JSON homogéneo con `code`, `message`, `request_id`; nunca se expone el stacktrace; errores de herramientas se devuelven al LLM como datos | `app/core/errors.py`, `app/agent/tools.py` |
| Autenticación y abuso | API key (comparación en tiempo constante, se registra solo su hash), rate limit por cliente | `app/api/deps.py` |
| Trazabilidad | Registro de cada interacción: pregunta (PII redactada), respuesta, herramientas y argumentos, fuentes, groundedness, flags de seguridad, modelo, versión de prompt, tokens, latencia | `app/agent/agent.py`, `app/storage/history.py` |
| Contenedor | Multi-stage, usuario no root (uid 10001), healthcheck, sin cabecera de servidor | `Dockerfile` |

## 2. Riesgos de IA y mitigaciones

| Riesgo | Mitigaciones implementadas | Evidencia |
| --- | --- | --- |
| **Prompt injection directa** | Detector ES/EN con normalización Unicode (anti ofuscación con caracteres invisibles) → bloqueo **antes** de llamar al LLM (sin costo ni superficie); los turnos bloqueados no se reinyectan como historial | INJ-01…04, HO-15/16, `test_security.py` |
| **Prompt injection indirecta** (en documentos o datos del legado) | Neutralización de oraciones con instrucciones en la ingesta y otra vez al devolver resultados; contenido de herramientas tratado como dato por el system prompt; reglas críticas deterministas | INJ-05 (anexo del proveedor), INJ-06 (SOL-1007) |
| **Fuga del system prompt** | Canario aleatorio por proceso en el prompt; si aparece en la salida se bloquea la respuesta | `test_output_guard_blocks_system_prompt_leak` |
| **Fuga de secretos / datos** | El LLM no tiene herramientas que lean secretos; patrones de secretos en la salida; PII redactada en logs e historial; solo campos permitidos de las solicitudes se exponen al LLM (`_public_request`) | INJ-03, `test_redaction_of_pii_in_logs` |
| **Respuestas no fundamentadas** | Umbral de relevancia + cobertura de términos → abstención; citas obligatorias; verificación de groundedness y de citas inválidas en cada respuesta (`grounding.grounded`) | NOINFO-01…04, HO-12…14, `test_hallucinated_answer_is_flagged_as_ungrounded` |
| **Agencia excesiva** | Herramientas de solo lectura/cálculo; no existe herramienta de aprobación o escritura; máx. 5 iteraciones; validación estricta de argumentos | INJ-07, `test_agent_stops_after_max_iterations` |
| **Costo / denegación de servicio** | Rate limit, longitud máxima de pregunta, `max_tokens`, límite de iteraciones, bloqueo previo al LLM, tamaño máx. de archivos | `test_rate_limit` |

## 3. Limitaciones conocidas (honestas)

- Las heurísticas de inyección son **evadibles** por un atacante decidido (paráfrasis, otros idiomas). Son una capa, no la defensa completa.
- La verificación de groundedness es **léxica**: detecta cifras o entidades inventadas, pero no contradicciones sutiles. En modo local es casi trivial porque las respuestas son extractivas.
- Las API keys son adecuadas para integración entre sistemas, no para identificar usuarios finales; no hay autorización por documento (todos los usuarios ven todo el corpus).
- El rate limit en memoria no se comparte entre réplicas.
- El modo local mantiene el índice en memoria del proceso (por eso un solo worker por réplica).

## 4. Recomendaciones para llevar a producción

### Seguridad
1. **Red privada**: Container Apps en VNet con ingress interno; *private endpoints* para OpenAI, AI Search, Cosmos, Key Vault y ACR; `publicNetworkAccess: Disabled`.
2. **Azure API Management** delante: validación de JWT de Entra ID, cuotas por consumidor, rate limiting distribuido, WAF (Application Gateway / Front Door).
3. **Autorización por documento** (*security trimming*): campo `allowed_groups` en el índice y filtro por los grupos del JWT del usuario; obligatorio antes de indexar información Confidencial.
4. **Azure AI Content Safety – Prompt Shields** (directa e indirecta) y *groundedness detection* como capa adicional a las heurísticas.
5. Microsoft Defender for Cloud (contenedores, Key Vault, AI), escaneo de imágenes en ACR, Dependabot/`pip-audit` y escaneo de secretos en CI.
6. Claves gestionadas por el cliente (CMK) si la clasificación de datos lo exige; data residency acorde a la política.

### Calidad y operación
7. **Evaluación continua**: el dataset como quality gate en cada PR; evaluadores de Azure AI Foundry (groundedness, relevance, coherence) sobre una muestra del tráfico real; revisión humana de respuestas con baja groundedness.
8. **Calibrar `MIN_RELEVANCE_SCORE`** con el reranker semántico real usando el dataset (el valor 0,40 es un punto de partida).
9. **Dashboards y alertas** en Application Insights: tasa de `no_info`, `blocked`, groundedness < 0,8, latencia p95, errores 5xx, tokens/costo; alerta de presupuesto al 80 % (exigencia del acta).
10. Versionado de prompts y de índices (índice nuevo + *alias swap* para re-indexaciones sin caída), despliegues por revisiones con tráfico gradual.
11. Ingesta orientada a eventos: Blob Storage (originales con versionado) → Event Grid → Container Apps Job; OCR con Document Intelligence para escaneados.
12. Capacidad: cuota TPM adecuada, reintentos con backoff (ya en el SDK), *circuit breaker*, caché semántica de preguntas frecuentes; evaluar PTU si el volumen es estable.
13. Continuidad: Cosmos con backup continuo, índice reconstruible desde Blob (fuente de verdad), despliegue de la plantilla en región secundaria.
14. Gobierno: retención (TTL 1 año en historial), derecho de supresión de datos personales, registro de decisiones de IA para auditoría (exigido por POL-SI-002 §5).
