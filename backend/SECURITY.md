# Seguridad del backend SeñaCL

Resumen de los controles implementados según OWASP API Security Top 10 (2023) y OWASP Top 10,
y de cómo verificarlos. Configuración en `.env` (ver `.env.example`).

## Control de acceso (API1 BOLA / API5 BFLA)

| Control | Implementación |
|---------|----------------|
| JWT obligatorio en historial | `Depends(get_current_user)` en `/api/history/*` (candado y botón **Authorize** en Swagger vía `HTTPBearer`). Sin token o con token inválido: `401`. |
| Propiedad en lectura | `GET /api/history/{user_id}` responde `403` si `user_id` no coincide con el `sub` del token. Ruta recomendada: `GET /api/history/me`. |
| Propiedad en borrado | `DELETE /api/history/{entry_id}` filtra por `id` **y** `user_id` en la misma consulta: una entrada ajena responde `404`, igual que una inexistente. |
| Escritura de historial | Se eliminó `session_id` del cuerpo de `/api/recognize` (permitía escribir en el historial de cualquier usuario). Ahora se persiste solo con JWT válido, `aceptada=true` y `save_history=true`. |
| IDs acotados | Path params `1..2147483647`: un ID fuera de `INT4` responde `422` en vez de `500`. |

## Autenticación (API2)

| Control | Implementación |
|---------|----------------|
| Hashing | **Argon2id** con `pwdlib[argon2]` (m=64 MiB, t=3, p=4), ejecutado fuera del event loop (`asyncio.to_thread`). Se retiró `passlib`/bcrypt. Los hashes bcrypt antiguos nunca autentican. |
| Política de contraseñas | `UserCreate`: 8–128 caracteres, al menos 1 mayúscula, 1 minúscula y 1 dígito. `EmailStr` (normalizado a minúsculas, máx. 100). Username `^[a-zA-Z0-9_.-]{3,50}$`. |
| Login dedicado | `UserLogin` (`username` + `password`, con topes de largo). |
| Anti-enumeración | Login: siempre `401 "Credenciales inválidas"`; si el usuario no existe se verifica contra un hash dummy (mismo costo Argon2id). Registro: `409` con mensaje genérico, y el hash se calcula antes de consultar para no filtrar existencia por tiempo. |
| JWT | PyJWT (se retiró `python-jose`, con CVE-2024-33663/33664 y dependencia `ecdsa` vulnerable). Algoritmo cerrado `["HS256"]` (nunca `none`), claims obligatorios `sub`, `exp`, `iat`, `jti`, `type="access"`. |
| Secreto | Con `DEBUG=false` el arranque **falla** si `SECRET_KEY` es el valor de ejemplo, tiene < 32 caracteres o muy poca variedad. |

## Consumo de recursos (API4) y validación de entrada

| Control | Implementación |
|---------|----------------|
| Tensores | REST y WS exigen exactamente 1629 números finitos por frame. `NaN`/`Infinity` se rechazan al parsear (`allow_inf_nan=False`) y de nuevo tras el cast a `float32` (p. ej. `1e300` se volvería `inf`). REST: `12 <= N <= 600`. |
| Cuerpo HTTP | `BodySizeLimitMiddleware`: > 5 MB → `413`, por `Content-Length` o contando bytes si llega *chunked*. |
| Binario REST | `application/octet-stream`: el largo debe ser múltiplo de 6516 bytes y `12 <= N <= 600`. |
| Rate limiting | En memoria, ventana deslizante de 60 s por IP: login 5/min, registro 3/min, recognize 30/min → `429` con `Retry-After`. Purga entradas expiradas, tope de 10 000 IPs rastreadas y `reset()` para tests. Es por proceso. |
| CPU de inferencia | `asyncio.Semaphore(MAX_CONCURRENT_INFERENCES=2)` **compartido** entre `POST /api/recognize` y `WS /ws/recognize`; NumPy/TensorFlow corren en `asyncio.to_thread`. |
| Errores 422 | El handler no devuelve el `input` rechazado (evita reflejar landmarks y el `500` por `NaN` no serializable). |

## WebSocket `/ws/recognize`

| Control | Código de cierre |
|---------|------------------|
| `Origin` en `ALLOWED_ORIGINS` (anti-CSWSH; sin `Origin` solo con `DEBUG=true`). Se rechaza antes del handshake. | `1008` (HTTP 403 en uvicorn) |
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
| CORS | Lista blanca desde `ALLOWED_ORIGINS` (se rechaza `*`), `allow_credentials=False` (el JWT va en header), métodos `GET/POST/DELETE/OPTIONS` y headers `Authorization`, `Content-Type`. |
| Cabeceras | En todas las respuestas: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy: camera=(self), microphone=(), geolocation=()`, `Cross-Origin-Opener-Policy`, `Content-Security-Policy: default-src 'none'` (excepto `/docs`) y `X-Request-ID`. `Cache-Control: no-store` en `/api/auth/*` y `/api/history/*`. HSTS con `DEBUG=false`. |
| Documentación | `/docs`, `/redoc` y `/openapi.json` deshabilitados con `DEBUG=false`. |
| Errores | Manejador global: el cliente recibe `{"detail": "Error interno del servidor", "request_id": ...}`; el traceback queda solo en el log del servidor con el mismo `request_id`. |
| Logs SQL | `echo=False` en SQLAlchemy (no vuelca emails ni hashes). |
| Seed | `python -m app.db.seed` se niega a correr con `DEBUG=false` (evita una cuenta con contraseña conocida en producción). |

## Privacidad por diseño (cero persistencia biométrica)

- Los frames y landmarks se procesan solo en RAM: no se escriben en disco, logs ni PostgreSQL.
- `history` guarda únicamente etiqueta, texto, confianza, modo y fecha.
- Los buffers del WebSocket son por conexión y se descartan al cerrar.
- Nunca se loguean contraseñas, tokens ni payloads de landmarks.

## Cadena de suministro

- Versiones fijadas en `requirements.txt`. Se retiraron `passlib`, `bcrypt`, `python-jose` (y `ecdsa`) y `python-multipart`, que no se usaba.
- Auditoría: `bandit -r backend/app -ll` y `pip-audit -r backend/requirements.txt`.

## Limitaciones conocidas

- Rate limiting y contadores del WS son en memoria y por proceso: con varios workers o réplicas,
  usar un almacén compartido (p. ej. Redis) o limitar en el proxy.
- La IP se toma de la conexión TCP. Detrás de un proxy inverso, configurarlo para que limite por IP
  real; no se confía en `X-Forwarded-For`.
- No hay revocación de JWT (lista de `jti`) ni refresh tokens; la expiración por defecto es 60 min.
- El backend no puede verificar que el cliente aplicó la `y` isotrópica ni que no espejó los landmarks.

## Reportar una vulnerabilidad

Escribir de forma privada al equipo mantenedor del repositorio; no abrir issues públicos con detalles explotables.
