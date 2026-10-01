# Evidencia: pruebas de seguridad en vivo contra Azure

Ejecutadas el 2026-10-01 contra `https://ca-ic7rag-dev-rumi5-api.bravestone-237448c2.eastus2.azurecontainerapps.io` (prompt `agent-v1.4`).

## 1. Autenticación — sin API key

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST $API/v1/chat -H 'Content-Type: application/json' -d '{"question":"hola"}'
```

Resultado: **401**. ✅ Confirmado: la API rechaza peticiones sin `X-API-Key`.

## 2. Rate limiting — ráfaga concurrente

Primero se intentó con 65 llamadas **secuenciales**: las 65 devolvieron `200`. Esto no prueba que el límite no funcione — con ~5 s de latencia real por pregunta (LLM real), 65 llamadas secuenciales tardan más de un minuto, así que nunca se acumulan suficientes peticiones dentro de la ventana deslizante de 60 s para activar el límite. **Lección: probar rate limiting contra un backend con latencia real requiere concurrencia, no solo volumen.**

Repetido con 65 llamadas en **paralelo** (20 concurrentes):

```
21 × 200
10 × 429
34 × 502
```

- **429 confirmado**: `{"error":{"code":"rate_limited","message":"Límite de peticiones excedido","details":{"limit_per_minute":60},"request_id":"..."}}` — límite de 60/min funcionando y con contrato de error limpio.
- **Hallazgo real no buscado**: 34 respuestas `502`. No es un bug de la API — es `upstream_error` limpio y correlacionable:
  ```json
  {"error":{"code":"upstream_error","message":"Fallo invocando Azure OpenAI","details":{"code":"rate_limit_exceeded"},"request_id":"..."}}
  ```
  Es decir: con ~20-25 llamadas reales simultáneas, **Azure OpenAI** (no nuestra app) empieza a limitar el throughput del deployment `gpt-5-mini` (capacidad `GlobalStandard=30`). La API absorbe ese fallo y responde con un contrato de error limpio, con `request_id`, sin stacktrace — exactamente el comportamiento que se esperaría de una "falla controlada" en producción, solo que surgió de una carga real en vez de tener que forzarla rompiendo una configuración.
  - **Mejora de producción identificada**: a ese nivel de concurrencia haría falta más capacidad TPM en el deployment, o un patrón de backpressure/retry-with-backoff en el cliente, antes de escalar el número de usuarios concurrentes reales.
  - Con una ráfaga más chica (15 concurrentes) no aparece el 502, solo 429: el límite propio de la app absorbe la carga moderada sin siquiera llegar a tocar el límite de Azure OpenAI.

## 3. Redacción de PII — hallazgo real y corregido

```bash
curl -s -X POST $API/v1/chat -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"question":"Soy ana@empresa.com, cel 3001234567, ¿estado de la SOL-1006?"}'
```

**Antes del fix**: `GET /v1/history/{interaction_id}` mostraba la pregunta guardada como:
`"Soy [EMAIL], cel 3001234567, ¿estado de la SOL-1006?"` — el correo se redactó, **el celular no**.

**Causa raíz**: el regex de teléfonos (`app/core/logging.py`) exigía un grupo de código de país de 1 a 3 dígitos (`\+?\d{1,3}`) seguido de área + prefijo + línea — es decir, mínimo 11 dígitos. Un celular colombiano típico sin separadores (`3001234567`, 10 dígitos) nunca podía calzar matemáticamente, sin importar el patrón de separadores. La prueba existente (`test_redaction_of_pii_in_logs`) solo cubría el formato `+57 300 123 4567`, por eso no se había detectado antes.

**Fix**: se volvió opcional el grupo completo del código de país (`(?:\+?\d{1,3}[ -]?)?`), no solo el signo `+`. Se agregó `test_redaction_of_phone_without_separators` como regresión. Verificado:

```bash
GET /v1/history/{interaction_id} → question: "Soy [EMAIL], cel [PHONE], ¿estado de la SOL-1006?"
```

Este hallazgo, por cómo se encontró (probando con datos reales contra el despliegue, no solo con el caso de prueba ya escrito), es evidencia de que "cumple con la prueba unitaria" y "protege el dato real" no siempre son lo mismo.

## Resumen

| Prueba | Resultado | Hallazgo |
| --- | --- | --- |
| Sin API key | 401 ✅ | — |
| Rate limit (app) | 429 ✅, contrato limpio | Requiere concurrencia real para activarse con latencia de LLM real |
| Throttling de Azure OpenAI bajo carga | 502 `upstream_error` limpio | Capacidad del deployment insuficiente para ~20+ llamadas reales simultáneas; mejora de producción identificada |
| Redacción de email | [EMAIL] ✅ | — |
| Redacción de teléfono sin separadores | ❌ → ✅ (corregido) | Regex no cubría el formato de celular sin separadores; corregido y con prueba de regresión |
