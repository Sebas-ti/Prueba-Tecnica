# Procedimiento de Continuidad, Respaldo y Recuperación de GESOL

Código: PR-OP-014 — Versión 2 — Dueño: Operaciones de TI

## 1. Objetivos de recuperación

- El objetivo de tiempo de recuperación (RTO) de GESOL es de 4 horas.
- El objetivo de punto de recuperación (RPO) de GESOL es de 24 horas.
- GESOL está clasificado como aplicación de criticidad media en el Análisis de Impacto al Negocio (BIA).

## 2. Política de respaldos

- Respaldo completo de la base de datos Oracle todos los días a las 11:00 p. m. con RMAN.
- Respaldo incremental de los archivos de adjuntos cada 6 horas.
- Los respaldos diarios se retienen 30 días; los respaldos de cierre de mes se retienen 12 meses.
- Una copia de los respaldos semanales se envía al centro de datos alterno.
- Las pruebas de restauración se ejecutan trimestralmente y su resultado se documenta en el informe de continuidad.

## 3. Procedimiento de recuperación ante caída del servidor de aplicaciones

1. Operaciones confirma la caída mediante la verificación de salud del balanceador.
2. Si solo falla un nodo, el balanceador redirige el tráfico al nodo sano y se abre una solicitud P2.
3. Si fallan ambos nodos, se declara incidente P1, se notifica a la Gerencia de Servicios Compartidos y se publica un aviso a los usuarios.
4. El equipo Aplicaciones Core reinicia los servicios de WebLogic; si no se recupera en 60 minutos, se activa el despliegue en el centro de datos alterno.

## 4. Procedimiento ante fallo del batch nocturno

Si JOB_CIERRE_DIARIO falla, Operaciones debe reintentarlo una única vez. Si el segundo intento falla, se registra una solicitud P3 al equipo Aplicaciones Core y el cierre se ejecuta manualmente al día siguiente. No se debe reintentar más de dos veces porque puede duplicar notificaciones a los usuarios.

## 5. Comunicación durante incidentes

Durante un incidente P1 se envía un comunicado a los usuarios cada 30 minutos hasta su resolución. Al cierre, se realiza un análisis de causa raíz (RCA) en un plazo máximo de 5 días hábiles.
