# Procedimiento de Gestión de Solicitudes Internas

Código: PR-TI-007 — Versión 6 — Vigente desde enero de 2026 — Dueño: Gerencia de Servicios Compartidos

## 1. Objetivo

Definir el ciclo de vida, la priorización, los acuerdos de nivel de servicio (SLA) y el escalamiento de las solicitudes internas registradas en GESOL.

## 2. Alcance

Aplica a todas las solicitudes de tecnología, infraestructura, accesos, reportes e integraciones registradas por colaboradores de la organización.

## 3. Ciclo de vida de una solicitud

Los estados válidos de una solicitud son, en orden: Registrada, En análisis, Aprobada, En ejecución, En validación y Cerrada. Adicionalmente existen los estados Rechazada y Bloqueada.

- Registrada: el solicitante creó la solicitud y está pendiente de triage.
- En análisis: la Mesa de Servicios valida la información y asigna prioridad y equipo responsable.
- Aprobada: el líder del área solicitante y el dueño del servicio aprobaron la solicitud.
- En ejecución: el equipo responsable está trabajando en la solución.
- En validación: el solicitante debe confirmar que la solución cumple lo pedido.
- Cerrada: la solicitud se completó y fue validada, o se cerró automáticamente.
- Bloqueada: la solicitud no puede avanzar por una dependencia externa o falta de información.
- Rechazada: la solicitud no procede; el motivo debe quedar documentado.

Una solicitud en estado En validación se cierra automáticamente si el solicitante no responde en 5 días hábiles. Una solicitud Bloqueada por más de 10 días hábiles debe escalarse al líder del equipo responsable.

## 4. Priorización

### 4.1 Definiciones

El impacto mide el alcance del problema: alto (afecta a toda la organización, a clientes o a un proceso crítico), medio (afecta a un área o equipo) o bajo (afecta a un usuario o es una mejora).

La urgencia mide qué tan rápido se requiere la solución: alta (se requiere de inmediato o hay operación detenida), media (se requiere en los próximos días) o baja (puede planificarse).

### 4.2 Matriz de prioridad

La prioridad se obtiene cruzando impacto y urgencia:

- Impacto alto y urgencia alta: P1 (Crítica).
- Impacto alto y urgencia media, o impacto medio y urgencia alta: P2 (Alta).
- Impacto alto y urgencia baja, impacto medio y urgencia media, o impacto bajo y urgencia alta: P3 (Media).
- Impacto medio y urgencia baja, impacto bajo y urgencia media, o impacto bajo y urgencia baja: P4 (Baja).

### 4.3 Reglas de ajuste

a) Toda solicitud relacionada con un incidente de seguridad de la información se eleva como mínimo a prioridad P2.

b) Una indisponibilidad de un sistema productivo con impacto alto siempre se clasifica como P1.

c) Un requerimiento regulatorio con fecha límite menor a 5 días hábiles se clasifica como P1.

## 5. Acuerdos de nivel de servicio (SLA)

| Prioridad | Tiempo de respuesta | Tiempo de resolución |
| P1 Crítica | 1 hora | 8 horas |
| P2 Alta | 4 horas | 2 días hábiles |
| P3 Media | 1 día hábil | 5 días hábiles |
| P4 Baja | 2 días hábiles | 10 días hábiles |

El SLA de resolución de una solicitud P1 es de 8 horas calendario, con atención 24x7. Para P2, P3 y P4 el SLA se mide en horario hábil, de lunes a viernes de 7:00 a. m. a 6:00 p. m.

El reloj del SLA se detiene mientras la solicitud está en estado Bloqueada por causas atribuibles al solicitante.

## 6. Escalamiento

- Primer nivel: Mesa de Servicios, canal #mesa-servicios o extensión 4500.
- Segundo nivel: líder del equipo responsable, cuando se consume el 75 % del SLA de resolución sin solución.
- Tercer nivel: Gerencia de Servicios Compartidos, cuando se incumple el SLA de una solicitud P1 o P2.

## 7. Aprobaciones

Las solicitudes de acceso a información clasificada como Confidencial requieren aprobación adicional del Oficial de Seguridad de la Información. Las solicitudes con costo estimado superior a 20 millones de pesos requieren aprobación del Comité de Inversiones de TI.
