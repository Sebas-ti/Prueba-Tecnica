# Manual Técnico del Sistema GESOL

Versión del documento: 4.1 — Última revisión: marzo de 2026 — Responsable: Arquitectura de Aplicaciones

## 1. Descripción general

GESOL (Gestor de Solicitudes Internas) es la aplicación corporativa donde los colaboradores registran, aprueban y hacen seguimiento a solicitudes internas de tecnología, infraestructura, accesos y reportes. Entró en producción en 2014 y la versión vigente es la 3.2.7.

GESOL atiende aproximadamente 1.200 usuarios activos al mes y registra en promedio 3.500 solicitudes mensuales. El pico de uso ocurre los primeros cinco días hábiles de cada mes por el cierre contable.

## 2. Arquitectura técnica

### 2.1 Componentes

- Capa de presentación: aplicación web Java 8 con el framework Struts 1.3 y páginas JSP.
- Servidor de aplicaciones: Oracle WebLogic Server 12c, desplegado en dos nodos en clúster activo-activo detrás de un balanceador F5.
- Base de datos: Oracle Database 12c Release 2, esquema GESOL_OWN, con un tamaño aproximado de 480 GB.
- Procesos batch: scripts de shell y PL/SQL programados con cron en el servidor batch01.
- Almacenamiento de adjuntos: recurso compartido NFS de 2 TB montado en /gesol/adjuntos.

### 2.2 Integraciones

- SAP HCM: integración SOAP para obtener la estructura organizacional y los aprobadores. Se sincroniza cada noche.
- Directorio Activo: autenticación de usuarios mediante LDAP (no soporta MFA de forma nativa).
- Correo corporativo: notificaciones por SMTP a través del relé interno smtp-relay01.
- Herramienta de monitoreo: los logs se escriben en archivos locales y se recolectan manualmente; no existe monitoreo centralizado.

### 2.3 Proceso batch nocturno

El proceso batch principal (JOB_CIERRE_DIARIO) se ejecuta todos los días a las 02:00 a. m. y tiene una duración promedio de 95 minutos. Realiza: cierre de solicitudes resueltas con más de 5 días sin respuesta del solicitante, recálculo de indicadores de SLA, sincronización con SAP HCM y depuración de sesiones.

Si el batch no termina antes de las 06:00 a. m., el equipo de Operaciones debe abortarlo y notificar a Arquitectura, porque bloquea tablas usadas por la operación diurna.

## 3. Limitaciones conocidas y deuda técnica

- Struts 1.3 está fuera de soporte desde 2013 y tiene vulnerabilidades conocidas; se mitigan con reglas en el WAF.
- El escalamiento es solo vertical; agregar un tercer nodo de WebLogic requiere licenciamiento adicional.
- Las búsquedas de texto sobre solicitudes históricas tardan más de 30 segundos porque no existe un motor de búsqueda.
- No hay API REST: otros sistemas consultan directamente vistas de la base de datos (VW_SOLICITUDES_EXT), lo que genera acoplamiento.
- Los adjuntos no tienen cifrado en reposo.

## 4. Ambientes

GESOL tiene tres ambientes: desarrollo (DEV), pruebas (QA) y producción (PRD). Los despliegues a producción se realizan únicamente en la ventana de mantenimiento de los sábados de 10:00 p. m. a 02:00 a. m., con aprobación previa del Comité de Cambios (CAB).

## 5. Contactos técnicos

El dueño funcional de GESOL es la Gerencia de Servicios Compartidos. El soporte de segundo nivel lo presta el equipo Aplicaciones Core y el soporte de base de datos el equipo DBA Oracle.
