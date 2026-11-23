---
name: appsec-owasp-hardening
description: Blindaje de ciberseguridad OWASP Top 10 y OWASP API Security Top 10 para FastAPI, PostgreSQL/Supabase, JWT, WebSockets, proxy inverso (Render), CORS (Vercel) e inferencia ML. Usar para auditar, endurecer o revisar cualquier código del backend antes de aprobarlo.
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
  - En WebSocket, rechazar mensajes individuales mayores a **48 KB** (`WS_MAX_MESSAGE_BYTES=49152` y `--ws-max-size 49152`; un frame binario pesa 6516 bytes y uno JSON sin redondear ~33 KB) y cerrar con código `1009`.
- **Rate Limiting y protección de CPU:**
  - Limitar intentos en `/api/auth/login` (ej. `5/minuto` por IP) y `/api/auth/register` (ej. `3/minuto` por IP).
  - Limitar `/api/recognize` (ej. `30/minuto` por IP/usuario).
  - En `WS /ws/recognize`: máximo **5 conexiones simultáneas por IP**, máximo **35 frames/segundo**, *idle timeout* de **60 segundos** y tope de inferencias concurrentes mediante `asyncio.Semaphore` (ej. 2–4 según CPU) para evitar saturación del servidor.
  - **RAM de Argon2id:** los hashes corren en un pool acotado (`MAX_CONCURRENT_HASHES`). Prohibido lanzarlos con `asyncio.to_thread` (una ráfaga de logins usaría 64 MiB por hilo) y prohibido bajar m/t/p para ahorrar memoria.

## 4. Seguridad de WebSockets (Anti-CSWSH)
- CORS estándar **no** protege WebSockets. En el handshake de `WS /ws/recognize`:
  - Validar explícitamente el header `Origin` contra `ALLOWED_ORIGINS` (en producción rechazar si falta o no coincide, cerrando con `1008 Policy Violation`).
  - Soportar autenticación JWT para usuarios registrados sin exponer el token en query params de logs (preferir primer mensaje de handshake `{"type": "auth", "token": "..."}` o `Sec-WebSocket-Protocol`).

## 5. CORS, Headers HTTP y Exposición de Información (OWASP API7 / API8)
- **CORS:** orígenes leídos desde `ALLOWED_ORIGINS` (reglas de nube en la sección 7). **Prohibido** `allow_origins=["*"]` cuando `allow_credentials=True`. Métodos y headers restringidos explícitamente.
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
- **Secretos:** prohibido subir `.env`, `DATABASE_URL`, la contraseña de la base, `service_role`/`anon` keys, `SECRET_KEY` o la CA privada de nadie. En `render.yaml` van con `sync: false`. `Settings` usa `hide_input_in_errors=True` y `core/db_url.py` nunca incluye la URL en sus errores: mantenerlo.

## 7. Seguridad en la nube (Supabase + Render + Vercel)
- **Supabase RLS:** toda tabla de `public` lleva Row Level Security **sin políticas** para `anon`/`authenticated` y con sus permisos revocados (`backend/db/supabase_rls.sql`, idempotente). Si se agrega una tabla a `schema.sql`, agregarla también ahí. El backend entra como `postgres` (dueño, `BYPASSRLS`): RLS **no** reemplaza los filtros por `user_id` de los repositorios. El frontend nunca usa la API de Supabase.
- **Reverse proxy (IP real):** toda IP sale de `core/network.py:obtener_ip_cliente()`.
  - `TRUST_PROXY_HOPS=0` (default local): se ignora `X-Forwarded-For` por completo.
  - `TRUST_PROXY_HOPS=N`: se toma la N-ésima entrada **desde la derecha**; si falta o alguna de esas N es inválida, se usa `client.host`. Nunca la primera de la izquierda ni `CF-Connecting-IP`/`X-Real-IP` sin verificar que el proxy los sobrescribe.
  - Un valor **mayor** al real permite falsificar la IP; uno **menor** agrupa a los clientes en un cupo. Ante la duda, quedarse corto y medir.
  - uvicorn siempre con `--no-proxy-headers`: Render define `FORWARDED_ALLOW_IPS=*` y uvicorn tomaría la entrada que escribe el atacante.
- **CORS / CSWSH:** `ALLOWED_ORIGINS` con `DEBUG=false` exige `https://` y rechaza `*`, rutas, credenciales y `http://` (única excepción: loopback `localhost`/`127.0.0.1`/`[::1]`). CORS y WebSocket comparten `Settings.origen_en_lista_blanca()`; no duplicar la lógica.
- **`ALLOWED_ORIGIN_REGEX`** (vacío por defecto): patrón cerrado validado en `core/origins.py`, jamás `.*`. En dominios compartidos (`vercel.app`) exige prefijo de proyecto y sufijo de equipo literales. Aun así, en `vercel.app` un tercero puede registrar un proyecto con un nombre que calce: usarlo solo en ambientes de prueba.
- **Redirecciones:** `redirect_slashes` apagado con `DEBUG=false` (un 307 apuntaría a `http://` detrás del proxy TLS).

## Checklist de Auditoría Obligatoria
1. Ejecutar `bandit -r backend/app -ll` → **0 hallazgos High/Medium**.
2. Ejecutar `pip-audit` (si está instalado) → revisar y mitigar CVEs críticos/altos.
3. Confirmar manualmente en tests: IDOR bloqueado (`403`/`404`), `NaN`/`Inf` bloqueado (`422`), payload > 5 MB bloqueado (`413`), Origin malicioso en WS rechazado (`1008`), rate limit activo (`429`), rotar `X-Forwarded-For` no evade el `429`.
4. Confirmar que `git status` no incluye `.env` ni URLs con credenciales.
