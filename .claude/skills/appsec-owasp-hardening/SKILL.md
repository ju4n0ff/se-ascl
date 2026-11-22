---
name: appsec-owasp-hardening
description: Blindaje de ciberseguridad OWASP Top 10 y OWASP API Security Top 10 para FastAPI, PostgreSQL, JWT, WebSockets e inferencia ML. Usar para auditar, endurecer o revisar cualquier código del backend antes de aprobarlo.
---

# Skill: Blindaje de Ciberseguridad (OWASP API + ML Real-Time)

## 1. Control de Acceso y Anti-BOLA / IDOR (OWASP API1)
- **Todas** las rutas de historial (`GET /api/history/{user_id}`, `DELETE /api/history/{entry_id}`) deben exigir JWT válido vía `Depends(get_current_user)` (visible con candado en OpenAPI/Swagger).
- En `GET /api/history/{user_id}`: verificar `current_user.id == user_id`; si no coincide, responder `403 Forbidden`. Agregar además `GET /api/history/me` como ruta recomendada.
- En `DELETE /api/history/{entry_id}`: filtrar por `History.id == entry_id` y `History.user_id == current_user.id`. Si no existe o pertenece a otro usuario, responder `404 Not Found` (no revelar si el ID existe para otro usuario).

## 2. Autenticación y Contraseñas (OWASP API2)
- **Hashing moderno:** migrar de `passlib` (sin mantenimiento) a **Argon2id** (`pwdlib[argon2]` o `argon2-cffi`). Actualizar `seed.sql` si usa hashes antiguos o documentar migración transparente.
- **Política de contraseñas en `UserCreate`:** longitud entre `8` y `128` caracteres, al menos 1 mayúscula, 1 minúscula y 1 dígito. Validar `EmailStr` y formato seguro de `username` (`^[a-zA-Z0-9_.-]{3,50}$`).
- **Anti-enumeración:** en `/api/auth/login` devolver siempre el mismo error genérico (`401 Unauthorized`, `"Credenciales inválidas"`) y ejecutar verificación de hash dummy cuando el usuario no exista para mitigar *timing attacks*. En `/api/auth/register`, devolver mensaje genérico `409 Conflict` sin detallar si chocó email o username.
- **JWT estricto:**
  - Fijar `ALGORITHM` permitido en lista cerrada (`["HS256"]`) y jamás aceptar `"none"`.
  - Validar `SECRET_KEY`: prohibir valores por defecto (`change-me-in-production`) cuando `DEBUG=false` y exigir mínimo 32 caracteres de entropía.
  - Incluir claims estándar `sub`, `exp`, `iat`, `jti` y `type: "access"`.

## 3. Validación Numérica y Anti-DoS en Inferencia ML (OWASP API4 / API8)
- **Validación estricta de tensores:** en REST y WebSocket rechazar con `422` / error estructurado cualquier frame que:
  - No tenga longitud exacta `1629`.
  - Contenga `NaN`, `Infinity` o `-Infinity` (`not np.isfinite(arr).all()`).
  - Tenga menos de `12` frames o más de `600` frames en REST.
- **Límites de tamaño de payload (anti-OOM):**
  - Middleware HTTP que rechace cuerpos mayores a **5 MB** con `413 Payload Too Large`.
  - En WebSocket, rechazar mensajes individuales mayores a **32 KB** (un frame JSON/binario de 1629 floats pesa ~7–16 KB) y cerrar con código `1009` si se abusa repetidamente.
- **Rate Limiting y protección de CPU:**
  - Limitar intentos en `/api/auth/login` (ej. `5/minuto` por IP) y `/api/auth/register` (ej. `3/minuto` por IP).
  - Limitar `/api/recognize` (ej. `30/minuto` por IP/usuario).
  - En `WS /ws/recognize`: máximo **5 conexiones simultáneas por IP**, máximo **35 frames/segundo**, *idle timeout* de **60 segundos** y tope de inferencias concurrentes mediante `asyncio.Semaphore` (ej. 2–4 según CPU) para evitar saturación del servidor.

## 4. Seguridad de WebSockets (Anti-CSWSH)
- CORS estándar **no** protege WebSockets. En el handshake de `WS /ws/recognize`:
  - Validar explícitamente el header `Origin` contra `ALLOWED_ORIGINS` (en producción rechazar si falta o no coincide, cerrando con `1008 Policy Violation`).
  - Soportar autenticación JWT para usuarios registrados sin exponer el token en query params de logs (preferir primer mensaje de handshake `{"type": "auth", "token": "..."}` o `Sec-WebSocket-Protocol`).

## 5. CORS, Headers HTTP y Exposición de Información (OWASP API7 / API8)
- **CORS:** orígenes leídos desde `ALLOWED_ORIGINS` en `.env` (ej. `http://localhost:4200`). **Prohibido** `allow_origins=["*"]` cuando `allow_credentials=True`. Métodos y headers restringidos explícitamente.
- **Headers de seguridad (middleware en todas las respuestas):**
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`
  - `Permissions-Policy: camera=(self), microphone=(), geolocation=()`
  - `Cache-Control: no-store` en endpoints de `/api/auth/*` y `/api/history/*`.
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains` cuando `DEBUG=false`.
- **Control de superficie:** desactivar `/docs`, `/redoc` y `/openapi.json` cuando `DEBUG=false`.
- **Manejador global de excepciones:** nunca retornar tracebacks, consultas SQL ni rutas de archivo al cliente; registrar el detalle completo solo en logs del servidor con un `request_id` correlacionado.

## 6. Privacy by Design y Cadena de Suministro
- **Cero persistencia biométrica:** jamás guardar frames de video, imágenes ni secuencias crudas de landmarks en disco, logs o PostgreSQL; procesarlos exclusivamente en RAM de forma efímera.
- **Logs limpios:** nunca loguear contraseñas, tokens `Authorization`, ni payloads de landmarks.
- **Dependencias:** fijar versiones en `requirements.txt` y auditar con `bandit` y `pip-audit`.

## Checklist de Auditoría Obligatoria
1. Ejecutar `bandit -r backend/app -ll` → **0 hallazgos High/Medium**.
2. Ejecutar `pip-audit` (si está instalado) → revisar y mitigar CVEs críticos/altos.
3. Confirmar manualmente en tests: IDOR bloqueado (`403`/`404`), `NaN`/`Inf` bloqueado (`422`), payload > 5 MB bloqueado (`413`), Origin malicioso en WS rechazado (`1008`), rate limit activo (`429`).