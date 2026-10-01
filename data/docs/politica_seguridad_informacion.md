# Política de Seguridad de la Información para Aplicaciones Internas

Código: POL-SI-002 — Versión 3 — Aprobada por el Comité de Seguridad en noviembre de 2025

## 1. Clasificación de la información

La información se clasifica en cuatro niveles: Pública, Interna, Confidencial y Restringida. Los datos personales de colaboradores y los datos financieros se consideran Confidenciales. Las credenciales, llaves criptográficas y secretos de aplicaciones se consideran Restringidos.

## 2. Gestión de accesos

- Todo acceso a aplicaciones internas debe solicitarse mediante GESOL y ser aprobado por el jefe inmediato y el dueño de la aplicación.
- Los accesos se revisan trimestralmente; los accesos no recertificados se revocan automáticamente.
- Las cuentas de colaboradores retirados deben deshabilitarse dentro de las 24 horas siguientes a la novedad de retiro.
- Los accesos privilegiados (administradores) requieren autenticación multifactor (MFA) y se otorgan por un máximo de 90 días.

## 3. Contraseñas y secretos

- Las contraseñas de usuario deben tener mínimo 12 caracteres y cambiarse cada 90 días.
- Está prohibido almacenar secretos, contraseñas o cadenas de conexión en el código fuente o en archivos de configuración versionados.
- Los secretos de aplicaciones deben almacenarse en un gestor de secretos aprobado (Azure Key Vault o AWS Secrets Manager) y rotarse como mínimo cada 180 días.
- Para cargas en la nube se debe preferir identidades administradas en lugar de secretos.

## 4. Retención y protección de datos

- Los registros de solicitudes y sus adjuntos se conservan durante 5 años y luego se eliminan de forma segura.
- Los registros de auditoría (logs de acceso y de interacciones) se conservan durante 1 año en almacenamiento inmutable.
- Los datos Confidenciales deben cifrarse en tránsito (TLS 1.2 o superior) y en reposo.
- Está prohibido usar datos de producción en ambientes de desarrollo o pruebas sin anonimizarlos previamente.

## 5. Uso de inteligencia artificial

- Solo se permiten servicios de IA generativa aprobados por Arquitectura y Seguridad, desplegados en la suscripción corporativa (por ejemplo, Azure OpenAI con acceso privado).
- No se debe enviar información Restringida a modelos de IA.
- Las respuestas generadas por IA que se usen para tomar decisiones deben citar sus fuentes y quedar registradas para auditoría.
- Los asistentes de IA deben contar con controles contra inyección de instrucciones (prompt injection) y filtrado de contenido.

## 6. Incidentes de seguridad

Cualquier sospecha de incidente de seguridad debe reportarse de inmediato al correo del CSIRT interno y registrarse en GESOL como solicitud de tipo incidente. El CSIRT debe dar respuesta inicial en máximo 1 hora.
