# Seguridad del backend SeñaCL

Resumen de los controles implementados según OWASP API Security Top 10 (2023) y OWASP Top 10,
y de cómo verificarlos. Configuración en `.env` (ver `.env.example`).

## Control de acceso (API1 BOLA / API5 BFLA)

| Control | Implementación |
|---------|----------------|
| JWT obligatorio en historial y perfil | `Depends(get_current_user)` en `/api/history/*` y `/api/users/*` (candado y botón **Authorize** en Swagger vía `HTTPBearer`). Sin token o con token inválido: `401`. |
| Propiedad en lectura | `GET /api/history/{user_id}` responde `403` si `user_id` no coincide con el `sub` del token. Ruta recomendada: `GET /api/history/me`. |
| Propiedad en edición y borrado | `PATCH` y `DELETE /api/history/{entry_id}` filtran por `id` **y** `user_id` en una sola sentencia (`UPDATE`/`DELETE ... RETURNING` en `HistoryRepository`): una entrada ajena responde `404`, igual que una inexistente. |
| Perfil sin identificador | `/api/users/me` toma el usuario del JWT: no hay `id` en la ruta que manipular. |
| Campos editables (API3) | `HistoryUpdate` solo acepta `spanish_text`; `UserUpdate` solo `email` y `new_password` (más `current_password`). `extra="forbid"`: cualquier otro campo responde `422`. |
| Consultas en un solo lugar | Todo acceso a `users` e `history` desde la API pasa por `app/db/repositories.py`, con parámetros enlazados. Un test estático impide consultas en `app/routes/`. |
| Escritura de historial | Se eliminó `session_id` del cuerpo de `/api/recognize` (permitía escribir en el historial de cualquier usuario). Ahora se persiste solo con JWT válido, `aceptada=true` y `save_history=true`. |
| IDs acotados | Path params `1..2147483647`: un ID fuera de `INT4` responde `422` en vez de `500`. |

## Autenticación (API2)

| Control | Implementación |
|---------|----------------|
| Hashing | **Argon2id** con `pwdlib[argon2]` (m=64 MiB, t=3, p=4), ejecutado fuera del event loop en un pool acotado (`MAX_CONCURRENT_HASHES`), para que una ráfaga de logins no agote la RAM. Se retiró `passlib`/bcrypt. Los hashes bcrypt antiguos nunca autentican. |
| Política de contraseñas | `UserCreate` y `UserUpdate` (mismo tipo `PasswordFuerte`): 8–128 caracteres, al menos 1 mayúscula, 1 minúscula y 1 dígito. `EmailStr` (normalizado a minúsculas, máx. 100). Username `^[a-zA-Z0-9_.-]{3,50}$`. |
| Cambio de email o contraseña | `PATCH /api/users/me` exige `current_password` (Argon2id en hilo) **antes** de tocar la base: un token robado no permite tomar la cuenta ni sondear emails. Error `401` genérico; email en uso, `409` genérico decidido por el `UNIQUE` de la base (sin condición de carrera). |
| Login dedicado | `UserLogin` (`username` + `password`, con topes de largo). Caracteres de control en `username` (p. ej. NUL) responden `422` sin llegar a PostgreSQL. |
| Anti-enumeración | Login: siempre `401 "Credenciales inválidas"`; si el usuario no existe se verifica contra un hash dummy (mismo costo Argon2id). Registro: `409` con mensaje genérico, y el hash se calcula antes de consultar para no filtrar existencia por tiempo. |
| JWT | PyJWT (se retiró `python-jose`, con CVE-2024-33663/33664 y dependencia `ecdsa` vulnerable). Algoritmo cerrado `["HS256"]` (nunca `none`), claims obligatorios `sub`, `exp`, `iat`, `jti`, `type="access"`. |
| Secreto | Con `DEBUG=false` el arranque **falla** si `SECRET_KEY` es el valor de ejemplo, tiene < 32 caracteres o muy poca variedad. |

## Consumo de recursos (API4) y validación de entrada

| Control | Implementación |
|---------|----------------|
| Tensores | REST y WS exigen exactamente 1629 números finitos por frame. `NaN`/`Infinity` se rechazan al parsear (`allow_inf_nan=False`) y de nuevo tras el cast a `float32` (p. ej. `1e300` se volvería `inf`). REST: `12 <= N <= 600`. |
| Cuerpo HTTP | `BodySizeLimitMiddleware`: > 5 MB → `413`, por `Content-Length` o contando bytes si llega *chunked*. |
| Binario REST | `application/octet-stream`: el largo debe ser múltiplo de 6516 bytes y `12 <= N <= 600`. |
| Rate limiting | En memoria, ventana deslizante de 60 s por IP: login 5/min, registro 3/min, `PATCH /api/users/me` 5/min, recognize 30/min → `429` con `Retry-After`. Purga entradas expiradas, tope de 10 000 IPs rastreadas y `reset()` para tests. Es por proceso. |
| CPU de inferencia | `asyncio.Semaphore(MAX_CONCURRENT_INFERENCES=2)` **compartido** entre `POST /api/recognize` y `WS /ws/recognize`; NumPy/TensorFlow corren en `asyncio.to_thread`. |
| Texto editable | `spanish_text`: 1–500 caracteres tras `strip`, sin caracteres de control (un NUL haría fallar el `UPDATE` con `500`). |
| Errores 422 | El handler no devuelve el `input` rechazado (evita reflejar landmarks y el `500` por `NaN` no serializable). |

## WebSocket `/ws/recognize`

| Control | Código de cierre |
|---------|------------------|
| `Origin` en `ALLOWED_ORIGINS` o `ALLOWED_ORIGIN_REGEX` (anti-CSWSH, misma función que CORS; sin `Origin` solo con `DEBUG=true`). Se rechaza antes del handshake. | `1008` (HTTP 403 en uvicorn) |
| Máximo 5 conexiones simultáneas por IP | `1008` |
| Mensaje > 48 KB (`WS_MAX_MESSAGE_BYTES`; además `--ws-max-size` a nivel de protocolo) | `1009` |
| Máximo 35 mensajes/s: los excedentes se descartan con un `error`; 5 ventanas seguidas excedidas cierran | `1008` |
| Inactividad de 60 s | `1001` |
| Frames con largo distinto de 1629 / 6516 bytes, `NaN`/`Inf` o tipos no numéricos | `error` controlado, la conexión sigue |
| Autenticación opcional con primer mensaje `{"type": "auth", "token": ...}` (nunca en la URL) | — |

Formato recomendado para el frontend: frames binarios `Float32Array` de 6516 bytes.

## Configuración y exposición (API8)

| Control | Implementación |
|---------|----------------|
| CORS | Lista blanca desde `ALLOWED_ORIGINS` (se rechaza `*`; con `DEBUG=false` se exige `https://` salvo loopback), `allow_credentials=False` (el JWT va en header), métodos `GET/POST/PATCH/DELETE/OPTIONS` y headers `Authorization`, `Content-Type`. |
| Cabeceras | En todas las respuestas: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy: camera=(self), microphone=(), geolocation=()`, `Cross-Origin-Opener-Policy`, `Content-Security-Policy: default-src 'none'` (excepto `/docs`) y `X-Request-ID`. `Cache-Control: no-store` en `/api/auth/*`, `/api/history/*` y `/api/users/*`. HSTS con `DEBUG=false`. |
| Documentación | `/docs`, `/redoc` y `/openapi.json` deshabilitados con `DEBUG=false`. |
| Errores | Manejador global: el cliente recibe `{"detail": "Error interno del servidor", "request_id": ...}`; el traceback queda solo en el log del servidor con el mismo `request_id`. |
| Secretos en errores | `hide_input_in_errors=True` en `Settings` y errores de URL sin la URL: un arranque fallido no vuelca `DATABASE_URL` ni `SECRET_KEY`. |
| Redirecciones | `redirect_slashes` apagado con `DEBUG=false`: detrás del proxy TLS el 307 apuntaría a `http://`. |
| Logs SQL | `echo=False` en SQLAlchemy (no vuelca emails ni hashes). |
| Seed | `python -m app.db.seed` se niega a correr con `DEBUG=false` (evita una cuenta con contraseña conocida en producción). |

## Nube: Supabase, Render y Vercel

| Control | Implementación |
|---------|----------------|
| RLS | `db/supabase_rls.sql` (idempotente): RLS en `users` e `history` sin políticas, permisos revocados a `anon` y `authenticated` (tablas, secuencias y privilegios por defecto). Evita fugas por PostgREST. El backend entra como `postgres`, que omite RLS: la autorización sigue en los repositorios. |
| TLS a la base | `DB_SSL` por `connect_args`. `require` cifra sin autenticar; con `DB_SSL_ROOT_CERT` verifica cadena y hostname. `sslmode=verify-*` nunca se degrada. Desactivarlo hacia Supabase deja un aviso en el log. |
| IP real | `core/network.py`: con `TRUST_PROXY_HOPS=N` toma la N-ésima entrada de `X-Forwarded-For` desde la derecha, validada con `ipaddress`; si falta o es inválida usa la conexión TCP. Con `0` ignora la cabecera. La comparten el rate limit y el tope de WebSockets. |
| uvicorn | `--no-proxy-headers`: por defecto reescribe la IP con `X-Forwarded-For`, y con el `FORWARDED_ALLOW_IPS=*` de Render tomaría la entrada que escribe el cliente. Un test lo comprueba con los flags reales de `render.yaml`. |
| Orígenes | `core/origins.py`: forma estricta `esquema://host[:puerto]`. `ALLOWED_ORIGIN_REGEX` usa una gramática cerrada (sin `.`, `\|`, grupos ni `*`), dominio literal y, en dominios compartidos, prefijo y sufijo literales. |
| Secretos | `render.yaml` declara `DATABASE_URL`, `SECRET_KEY` y `ALLOWED_ORIGINS` con `sync: false`. Nunca subir `.env`, URLs con contraseña ni la `service_role` key. |
| Tests | `conftest.py` aborta si la base no termina en `_test` o el servidor no es local. |

## Privacidad por diseño (cero persistencia biométrica)

- Los frames y landmarks se procesan solo en RAM: no se escriben en disco, logs ni PostgreSQL.
- `history` guarda únicamente etiqueta, texto, confianza, modo y fecha.
- Derechos del titular (Ley 21.719): acceso (`GET /api/users/me`, `GET /api/history/me`), rectificación
  (`PATCH`) y supresión (`DELETE /api/users/me`, que borra el historial por `ON DELETE CASCADE`).
- Los buffers del WebSocket son por conexión y se descartan al cerrar.
- Nunca se loguean contraseñas, tokens ni payloads de landmarks.

## Cadena de suministro

- Versiones fijadas en `requirements.txt`. Se retiraron `passlib`, `bcrypt`, `python-jose` (y `ecdsa`) y `python-multipart`, que no se usaba.
- Auditoría: `bandit -r backend/app -ll` y `pip-audit -r backend/requirements.txt`.

## Limitaciones conocidas

- Rate limiting y contadores del WS son en memoria y por proceso: con varios workers o réplicas,
  usar un almacén compartido (p. ej. Redis) o limitar en el proxy.
- `TRUST_PROXY_HOPS` debe coincidir con la infraestructura real. Render no documenta cuántas entradas
  agrega: un valor menor agrupa a todos los clientes en un mismo cupo (fácil de agotar por un atacante);
  uno mayor permite falsificar la IP. Procedimiento de verificación en `README.md`.
- El rate limit es por IP exacta: un cliente IPv6 puede rotar direcciones dentro de su /64.
- `DB_SSL=true` sin `DB_SSL_ROOT_CERT` no autentica al servidor de base de datos.
- `ALLOWED_ORIGIN_REGEX` sobre `vercel.app` puede calzar con el proyecto de un tercero; no usar en producción.
- En modo Transaction, las sentencias preparadas con nombre único pueden quedar en el backend del pooler
  hasta que este recicle la conexión. No se ha probado contra un PgBouncer/Supavisor real.
- No hay revocación de JWT (lista de `jti`) ni refresh tokens; la expiración por defecto es 60 min.
  Cambiar la contraseña no invalida los tokens ya emitidos (borrar la cuenta sí: el usuario deja de existir).
- `DELETE /api/users/me` no vuelve a pedir la contraseña (un `DELETE` no lleva cuerpo, RFC 9110): quien
  tenga un token vigente puede borrar la cuenta. El cliente debe confirmar la acción con el usuario.
- El backend no puede verificar que el cliente aplicó la `y` isotrópica ni que no espejó los landmarks.

## Reportar una vulnerabilidad

Escribir de forma privada al equipo mantenedor del repositorio; no abrir issues públicos con detalles explotables.
