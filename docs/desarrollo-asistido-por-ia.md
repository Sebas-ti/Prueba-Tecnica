# Desarrollo asistido por IA (AI-CDL)

Esta sección responde al punto 5.4 de la prueba. La escribo en primera persona, como
candidato: qué hice yo, qué le pedí a la herramienta, qué validé yo mismo y dónde tuve
que corregirla o frenarla. Hay dos fases: la construcción inicial del proyecto, y una
sesión posterior de validación en vivo contra Azure real, feedback externo y
correcciones — esta segunda fase es la que más defectos reales expuso, precisamente
porque dejó de ser código revisado y pasó a ser un sistema operando con datos y tráfico
reales.

## 1. Herramienta utilizada

- **Claude Code** (Claude Sonnet 5, Anthropic), con acceso a shell, Python, `az` CLI,
  Docker/ACR y Git. Lo usé de forma agéntica: le pedí objetivos ("despliega en Azure",
  "corre la evaluación real", "corrige esto que encontró el revisor") y lo dejé
  ejecutar, leer errores y corregir, revisando yo el resultado en cada paso.
- Equivalentes válidos para el mismo flujo: GitHub Copilot (agent mode), Cursor, Kiro,
  OpenAI Codex.

## 2. Tareas que delegué, y cuánto control mantuve

| Tarea | Grado de apoyo | Qué validé yo / dónde intervine |
| --- | --- | --- |
| Estructura del repositorio y puertos/adaptadores | Alto | Revisé contra los criterios de la prueba antes de aceptar el diseño |
| Código de API, RAG, agente, herramientas | Alto | 69 pruebas automatizadas + pruebas de humo contra la API real en Azure |
| Despliegue real en Azure (no solo IaC en papel) | Alto, pero yo ejecuté cada paso sensible | Confirmé antes de crear recursos; corrí yo mismo los comandos que tocaban secretos o permisos (ver sección 4) |
| Corrección de un defecto reportado por un revisor externo | Alto | Verifiqué el fix contra el despliegue real antes de darlo por cerrado, no solo contra la prueba unitaria |
| Evaluación con LLM real + juez | Medio-alto | Yo decidí correr 3 veces (principal, repetición, held-out) para medir variabilidad, no solo aceptar un único número |
| Frontend de demostración (consola web) | Alto | Lo pedí explícitamente como "bonus", fuera del alcance obligatorio; lo probé yo en el navegador en cada iteración |
| Diagrama y documentación | Alto | Revisión visual y de contenido antes de aceptar |

## 3. Validaciones que hice sobre lo que la IA produjo o ejecutó

1. **No acepté el despliegue en Azure como "hecho" hasta probarlo yo**: pedí preguntas
   reales contra la API (`curl`, Swagger, mi propia consola), no solo que el `az
   deployment group create` terminara en verde.
2. **Cuando el asistente se bloqueó solo, lo dejé bloqueado**: dos veces el propio
   clasificador de la herramienta rechazó una acción que el asistente iba a tomar por
   su cuenta (darse un rol de permisos en Key Vault, y luego abrir `CORS_ORIGINS=*` en
   la API pública). En ambos casos el asistente no intentó rodear el bloqueo — me
   explicó qué necesitaba y por qué, y yo decidí: la lectura de secretos la hice yo
   mismo desde mi propia terminal (nunca pasó por el chat), y el CORS abierto lo
   reemplazamos por completo sirviendo la consola desde el mismo origen (`/console`)
   en vez de forzar el permiso.
3. **Cuando un revisor externo me dio feedback detallado**, no apliqué sus sugerencias
   a ciegas: antes de pedirle al asistente que corrigiera algo, comparé cada punto
   contra el estado real del repo — dos de sus observaciones ya estaban resueltas (la
   evaluación contra Azure ya existía), así que no las re-hice; prioricé las que sí
   eran nuevas y reales.
4. **Probé el fix del "no prometas lo que no puedes hacer" contra el despliegue real**,
   no solo contra el caso de prueba que el propio asistente escribió para verificarlo
   — y encontré que el caso de prueba tenía un bug (ver abajo) que el asistente no
   había anticipado.
5. **Corrí la evaluación formal tres veces** (principal, repetición, held-out) porque
   un solo número contra un LLM real no es evidencia suficiente de nada — fue decisión
   mía, no una sugerencia que acepté pasivamente.
6. **Reproduje yo mismo cada hallazgo de seguridad antes de documentarlo**: el 401 sin
   clave, el 429 de mi propio límite, y el 502 de capacidad de Azure OpenAI los vi con
   mis propias pruebas contra la API real, no los tomé de la palabra del asistente.

## 4. Riesgos y defectos reales encontrados — fase 1 (construcción inicial)

Estos defectos fueron introducidos por la IA y detectados por pruebas automatizadas o
revisión de código, antes de desplegar nada a Azure real:

| # | Defecto | Cómo se detectó | Impacto si no se detecta |
| --- | --- | --- | --- |
| 1 | `.env.example` con comentarios en línea se leía como parte del valor de la clave | Carga manual de `Settings` desde el ejemplo | Autenticación con una clave predecible publicada en el repo |
| 2 | La dependencia de autenticación leía configuración global, no la de la app | Prueba de integración falló (200 en vez de 401) | Endpoints sin autenticación en ciertos despliegues |
| 3 | Clave `args` reservada en logging tumbaba cada ejecución de herramienta | 8 pruebas fallaron con `KeyError` | Caída del agente en producción en la primera herramienta |
| 4 | Detector de inyección no reconocía una forma enclítica común | Prueba parametrizada de inyección | Evasión trivial del guardrail |
| 5 | Neutralización de inyección borraba líneas completas, perdiendo contenido legítimo | Revisión manual de la salida | Pérdida de información útil |
| 6 | `pypdf` en una versión con CVEs conocidos | Revisión de versiones antes de fijar `requirements.txt` | Riesgo de seguridad en la ingesta de PDFs |
| 7 | Falsos positivos de RAG en preguntas fuera de dominio con palabras ambiguas | Pruebas exploratorias | Respuesta no fundamentada presentada como cierta |
| 8 | Sobreajuste del dataset de evaluación (umbrales calibrados con las mismas preguntas) | Análisis del propio proceso | Métricas infladas |
| 9 | Diagrama con textos desbordados | Render a PNG y revisión visual | Entregable poco profesional |
| 10 | La IaC apuntaba a un modelo ya deprecado en Azure | Verificación del calendario oficial de modelos | Despliegue fallido en la suscripción del evaluador |
| 11 | El historial en Cosmos usaba una operación no soportada por el SDK de Python entre particiones | Revisión del SDK instalado | `/v1/history` fallando solo en Azure |

## 4bis. Riesgos y defectos reales — fase 2 (validación en vivo contra Azure)

Esta fase expuso una categoría de defectos que la fase 1 **no podía** encontrar, porque
solo aparecen con infraestructura real, tráfico real y datos adversariales reales:

| # | Defecto / hallazgo | Cómo lo encontré | Gravedad |
| --- | --- | --- | --- |
| 12 | El despliegue de Azure AI Search falló por falta de capacidad regional (`InsufficientResourcesAvailable`) | Error real de ARM al desplegar, no algo que una prueba unitaria detecte | Bloqueaba todo el despliegue; se resolvió separando la región de Search de la de OpenAI |
| 13 | Dos builds de ACR y una corrida de evaluación local "fallaron" por un bug de codificación de consola de Windows (`cp1252`), no por un error real | Comparé el estado real del build en Azure (`az acr task list-runs`) contra el crash local antes de reintentar — evité relanzar builds innecesarios | Bajo, pero habría desperdiciado tiempo y cómputo si hubiera confiado ciegamente en el código de salida del CLI |
| 14 | **Un revisor externo encontró que el agente ofrecía capacidades inexistentes** ("puedo enviarte el documento por correo") al final de una respuesta | Revisión humana del comportamiento real, no de pruebas | Alto: es exactamente lo que penaliza el criterio de "respuestas no fundamentadas" |
| 15 | El caso de prueba que escribí para verificar el fix del punto 14 tenía su propio bug: buscaba la subcadena "puedo enviar" como prohibida, pero esa subcadena también aparece dentro de su propia negación ("**no** puedo enviar") | Lo detecté leyendo el texto completo del reporte de evaluación, no solo el símbolo ✅/❌ | Medio: un falso positivo me habría hecho creer que el fix no funcionaba cuando sí funcionaba |
| 16 | El runner de evaluación no manejaba el caso en que **el propio filtro de contenido de Azure OpenAI bloquea la llamada al juez** (el texto adversarial de un caso de inyección, embebido en el prompt del juez, dispara el detector de jailbreak de Azure) | La corrida completa abortaba a mitad de camino | Medio: sin el fix, no se podía evaluar nada después del primer caso de inyección |
| 17 | **Gap real de redacción de PII**: un celular sin separadores (`3001234567`, formato común en Colombia) nunca se redactaba a `[PHONE]`, aunque la prueba unitaria existente (con `+57 300 123 4567`) pasaba — el regex exigía matemáticamente un mínimo de 11 dígitos | Probé con datos realistas contra el historial real en Cosmos, no solo con el caso de prueba ya escrito | Alto: fuga de datos personales reales en el historial de interacciones |
| 18 | Subí sin querer, probando la función de carga de documentos de mi propia consola, un archivo de **otro proyecto mío** (instrucciones internas, sin relación con GESOL) y el `.docx` de esta misma prueba técnica — ambos quedaron indexados y el agente empezó a responder preguntas sobre ellos | Le pregunté directamente al agente qué contenía un archivo con un nombre que no reconocía | Alto: riesgo real de mezclar datos de un proyecto con otro, y de exponer contenido no destinado al corpus en un video público |
| 19 | Bajo carga concurrente moderada (20-25 llamadas reales simultáneas), el propio **Azure OpenAI** empieza a limitar el throughput del deployment (`rate_limit_exceeded`), no solo mi límite de aplicación | Prueba de carga real, no simulada | Informativo: es una limitación de capacidad de la suscripción de prueba, no un bug — pero hay que saberlo antes de escalar a más usuarios |

## 5. Cómo evité depender ciegamente de la herramienta

- **"Confía, pero ejecuta"**: ningún cambio se dio por terminado sin correr pruebas, la
  evaluación, o una llamada real a la API desplegada — esto incluyó repetir la
  evaluación completa después de cada fix para confirmar que el número cambiaba por la
  razón correcta.
- **Contratos primero**: esquemas Pydantic, JSON Schema de herramientas y contratos de
  API definidos explícitamente; la IA rellena implementaciones verificables contra
  esos contratos, no al revés.
- **Acciones sensibles, las ejecuté yo**: cuando la herramienta necesitaba leer un
  secreto de Key Vault o ampliar un permiso, no delegué esa decisión — la ejecuté yo
  mismo en mi propia terminal, fuera del chat, precisamente para que el valor nunca
  quedara expuesto en la conversación.
- **Nunca dejé que un comando destructivo o de creación de recursos corriera sin que
  yo entendiera y aprobara qué iba a hacer** — incluidos los redeploys, el borrado de
  documentos del índice y los cambios de configuración del Container App.
- **Lógica crítica fuera del LLM**: las reglas de negocio (prioridad, esfuerzo) siguen
  siendo deterministas y probadas; ni siquiera el LLM real las calcula de memoria.
- **Evaluación independiente** (set held-out) y, en Azure, LLM-juez como segunda
  opinión cualitativa, no como verdad absoluta — el propio juez discrepó del harness
  de texto exacto varias veces, y en esos casos confié en el juez.
- **Leí los reportes de evaluación línea por línea**, no solo el número agregado —
  así fue como encontré el bug del caso de prueba (punto 15) y entendí que varios
  "fallos" eran en realidad diferencias de formato que el propio juez calificaba como
  correctas.

## 6. Cómo lo usaría en equipo (propuesta de práctica)

1. Especificación breve (objetivo, contratos, criterios de aceptación) antes de pedir
   código.
2. Generación por incrementos pequeños, con pruebas en el mismo cambio.
3. **Ninguna acción contra infraestructura real sin confirmación explícita** —
   funcionó bien en esta sesión: el asistente explicaba qué iba a crear/borrar y
   esperaba luz verde, y cuando el propio sistema lo bloqueaba por tocar secretos o
   debilitar seguridad, no insistía por otra vía.
4. Pull request con plantilla que declare qué generó la IA y qué se validó.
5. Quality gates en CI: lint, pruebas, evaluación con umbral, escaneo de dependencias.
6. Revisión por pares enfocada en seguridad, manejo de datos y supuestos de negocio —
   y, como mínimo, una corrida de la evaluación contra el entorno real antes de
   confiar en el número del modo local.
