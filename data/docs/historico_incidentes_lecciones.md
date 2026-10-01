# Registro Histórico de Incidentes y Lecciones Aprendidas de GESOL

Documento consolidado por Gestión de Problemas — Periodo 2023 a 2026

## Incidente INC-2023-114: tablespace lleno

En agosto de 2023 GESOL estuvo indisponible durante 6 horas porque el tablespace GESOL_DATA llegó al 100 % de ocupación durante el cierre de mes. La causa raíz fue la ausencia de alertas de capacidad y el crecimiento no controlado de la tabla de auditoría.

Lección aprendida: se configuró una alerta cuando el tablespace supera el 85 % y se implementó una purga mensual de la tabla de auditoría con más de 13 meses de antigüedad.

## Incidente INC-2024-052: fallo de integración con SAP HCM

En marzo de 2024 la sincronización con SAP HCM falló durante 3 días seguidos por el vencimiento del certificado TLS del servicio SOAP. Como consecuencia, 214 solicitudes quedaron sin aprobador asignado.

Lección aprendida: los certificados de integraciones se registran en el inventario de certificados con alertas 30 días antes del vencimiento.

## Incidente INC-2024-201: lentitud en cierre de mes

En noviembre de 2024 los tiempos de respuesta superaron los 20 segundos durante el cierre contable porque el batch nocturno se extendió hasta las 9:00 a. m. La causa fue un índice faltante en la tabla SOL_HISTORIAL después de una migración de datos.

Lección aprendida: toda migración de datos debe incluir una validación de planes de ejecución y una prueba de rendimiento en QA con volumen similar a producción.

## Proyecto fallido de migración en 2025

En el primer semestre de 2025 se intentó migrar GESOL a una versión más reciente de WebLogic sin cambiar el framework Struts. El proyecto se suspendió tras 4 meses porque Struts 1.3 presentaba incompatibilidades y el costo superó el presupuesto en 40 %.

Lección aprendida: el Comité de Arquitectura recomendó no invertir más en actualizar la plataforma actual y, en su lugar, modernizar GESOL de forma incremental usando el patrón strangler fig, empezando por exponer APIs y por las capacidades de búsqueda y consulta.

## Indicadores históricos

- Disponibilidad promedio de GESOL en 2025: 99,1 %.
- Cumplimiento de SLA de solicitudes P1 en 2025: 87 %.
- Cumplimiento de SLA de solicitudes P3 en 2025: 93 %.
- Tiempo promedio que un analista dedica a buscar información en documentos y solicitudes históricas: 25 minutos por solicitud.
