# SeñaCL Backend

## Requisitos

- Python 3.11+
- PostgreSQL 14+
- TensorFlow 2.16.2 + Keras 3.15.1 (modelo LSCh v3, CPU)

## Instalación

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

## Configuración

```powershell
copy .env.example .env
```

Editar `.env` con tus credenciales de PostgreSQL. Variables clave:

| Variable | Descripción |
|----------|-------------|
| `DEBUG` | `false` por defecto. Con `false`: sin `/docs`, HSTS activo, WS exige `Origin` y el arranque falla si `SECRET_KEY` es débil. |
| `SECRET_KEY` | Mínimo 32 caracteres aleatorios. Generar con `python -c "import secrets; print(secrets.token_urlsafe(64))"`. |
| `ALLOWED_ORIGINS` | Orígenes permitidos para CORS y para el `Origin` del WebSocket, separados por comas (sin `*`). |
| `DYNAMIC_MODEL_PATH`, `LABELS_PATH`, `FEATURES_CONFIG_PATH` | Artefactos del modelo v3 (relativos a `backend/`). |
| `MAX_BODY_BYTES`, `RATE_LIMIT_*`, `WS_*` | Límites anti-DoS (ver `.env.example` y `SECURITY.md`). |

## Base de datos

PostgreSQL corre en WSL y se accede desde Windows en `127.0.0.1:5432`. Desde una terminal WSL:

```bash
sudo -u postgres createdb signia
psql -h 127.0.0.1 -U postgres -d signia -f db/schema.sql
psql -h 127.0.0.1 -U postgres -d signia -f db/seed.sql     # opcional, solo desarrollo
```

El seed también se puede cargar desde Windows sin `psql` (idempotente, solo con `DEBUG=true`):

```powershell
python -m app.db.seed
```

Usuario de prueba: `test_user` / `Test1234!` (hash Argon2id). Las cuentas creadas antes de la
migración a Argon2id (hashes bcrypt) ya no pueden iniciar sesión: hay que registrarlas de nuevo.

## Levantar el servidor

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --ws-max-size 49152
```

`--ws-max-size` aplica el tope de 48 KB por mensaje WebSocket también a nivel de protocolo
(`python -m app.main` ya lo configura). Documentación interactiva (solo con `DEBUG=true`):
http://localhost:8000/docs (botón **Authorize** para pegar el JWT).

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/auth/register` | Registro (3/min por IP; `409` genérico si ya existe) |
| POST | `/api/auth/login` | Login JSON `{username, password}`, devuelve JWT (5/min por IP) |
| POST | `/api/recognize` | Reconocimiento de una secuencia `(N, 1629)`; JWT opcional (30/min por IP) |
| GET | `/api/history/me` | 🔒 Historial del usuario autenticado |
| GET | `/api/history/{user_id}` | 🔒 Historial propio (`403` si `user_id` no es el del token) |
| DELETE | `/api/history/{entry_id}` | 🔒 Borrar entrada propia (`404` si no existe o es ajena) |
| GET | `/api/health` | Estado de PostgreSQL y del modelo v3 (503 si está degradado) |
| GET | `/api/clases` | Glosario de las 89 señas soportadas |
| WS | `/ws/recognize` | Reconocimiento en streaming, frame a frame |

## Contrato de landmarks (modelo LSCh v3)

Cada frame es un vector de **1629 floats** en este orden (ver `README_ML.md`):
Pose 33×3 + Rostro 468×3 (`refineFaceLandmarks=false`) + Mano Izq 21×3 + Mano Der 21×3.
Cada punto se envía como `[x, y * (alto / ancho), z]`; un bloque no detectado va en `0.0`.
**Nunca** espejar los landmarks (el espejo es solo visual, por CSS).

### `POST /api/recognize`

```json
{ "frames": [[0.51, 0.24, -0.32, "... 1629 floats"], "..."], "mode": "dynamic", "top_k": 3 }
```

- `12 <= len(frames) <= 600`, cada frame con exactamente 1629 números finitos (si no, `422`).
- Alternativa binaria (recomendada para secuencias largas): `Content-Type: application/octet-stream`
  con un `Float32Array` little-endian de `N * 1629` valores (`N * 6516` bytes). `top_k`,
  `save_history` y `mode` van como query params: `POST /api/recognize?top_k=3&save_history=true`.
- Cuerpo máximo: 5 MB (`413`). En JSON sin redondear eso alcanza para ~150 frames; con 5
  decimales, ~340; en binario caben los 600.
- Con `Authorization: Bearer <token>`, `save_history: true` y `aceptada: true` la predicción se
  guarda en `history` (`guardado_en_historial: true`). Sin token la inferencia funciona igual pero
  no se guarda; un token inválido responde `401`.
- El servidor remuestrea a 30 frames (`linspace(...).round()` si `N >= 30`, zero-padding si `N < 30`).

Respuesta:

```json
{
  "aceptada": true,
  "prediccion": {"clase_raw": "donde_salida.I", "texto": "¿donde salida?", "es_pregunta": true, "confianza": 0.8742},
  "top_k": [{"clase_raw": "donde_salida.I", "texto": "¿donde salida?", "es_pregunta": true, "confianza": 0.8742}],
  "frames_recibidos": 38,
  "latencia_ms": 6.1,
  "predicted_label": "donde_salida.I",
  "spanish_text": "¿donde salida?",
  "confidence": 0.8742,
  "mode": "dynamic",
  "timestamp": "2026-11-22T12:00:00Z"
}
```

`mode: "static"` usa el SVM opcional `models/static_svm.joblib`; si no existe responde `503`.

## WebSocket `/ws/recognize`

Cliente → servidor:

| Mensaje | Efecto |
|---------|--------|
| Binario `Float32Array` (6516 bytes, little-endian) — **recomendado para el frontend** | Agrega un frame |
| `{"type": "frame", "data": [1629 floats]}` (~33 KB sin redondear; útil para pruebas) | Agrega un frame |
| `{"type": "config", "modo": "auto" \| "manual", "umbral": 0.55, "top_k": 3, "save_history": false}` | Configura la sesión |
| `{"type": "auth", "token": "<JWT>"}` | Autentica la sesión (habilita `save_history`) |
| `{"type": "manual_start"}` / `{"type": "manual_stop"}` | Grabación manual (tope 600 frames) |
| `{"type": "reset"}` | Vacía el buffer |

Modo automático (igual que `conversor/test_local.py`): empieza a grabar tras 3 frames seguidos con
alguna mano, corta tras 10 frames sin manos o al llegar a 90, y descarta segmentos de menos de 12 frames.

Límites: `Origin` debe estar en `ALLOWED_ORIGINS` (sin `Origin` solo con `DEBUG=true`), máximo 5
conexiones por IP, 48 KB por mensaje (`1009`), 35 mensajes/s (los excedentes se descartan con un
error; si persiste, `1008`) y 60 s de inactividad (`1001`). El JWT nunca va en la URL.

Servidor → cliente: `{"type": "estado", ...}`, `{"type": "prediccion", ...}` (mismo contrato que REST
más `origen` y `aviso`), `{"type": "descartado", "motivo": "ruido", ...}` y `{"type": "error", ...}`.

## Modelos

- **Dinámico (oficial):** `models/mejor_modelo_lsch.keras` + `models/etiquetas_lsch.json` +
  `models/config_features.json` + `app/ml/features_lsch.py` (copias 1:1 de `conversor/`).
  Se carga una sola vez al arrancar; si `config_features.json` no coincide, el servidor no arranca.
- **Estático (opcional):** `models/static_svm.joblib`. Si falta, el modo `static` queda deshabilitado
  y `/api/health` lo informa como `no_disponible`.

Las rutas se configuran con `DYNAMIC_MODEL_PATH`, `LABELS_PATH`, `FEATURES_CONFIG_PATH` y
`STATIC_MODEL_PATH` (relativas a `backend/`).

## Tests y quality gates

La suite (`tests/`) corre contra la base aislada **`signia_test`** (nunca `signia`): la URL sale de
`TEST_DATABASE_URL` (por defecto `postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/signia_test`)
y la sesión se aborta si el nombre de la base no termina en `_test`. Las tablas se truncan antes de
cada test y el rate limiter se reinicia. La configuración de los tests no depende de `backend/.env`.

```powershell
pip install -r requirements-dev.txt
# desde la raíz del repo
ruff check backend/app backend/tests
bandit -r backend/app -ll
pytest backend/tests -v
```

| Archivo | Cubre |
|---|---|
| `test_ml_parity.py` | Paridad hasta el 4.º decimal contra `conversor/features_lsch.py` (JSON y binario, N=15/30/45), artefactos 1:1, remuestreo, formateo `.I`, semáforo |
| `test_security.py` | Auth/JWT manipulados, anti-BOLA/IDOR, NaN/Inf, 413 (Content-Length y chunked), 415, 429, cabeceras, CORS, handler 500, WebSocket (Origin, 1009, 1001, límites) |
| `test_auth_history.py` | Health, Argon2id, historial y reglas de persistencia de `/api/recognize` |
| `test_websocket.py` | Máquina de estados: modo auto, ruido descartado, modo manual, aislamiento y persistencia |
| `test_config_prod.py` | Validación de `Settings`, app con `DEBUG=false` (subproceso), seed idempotente |

## Seguridad

Ver [`SECURITY.md`](SECURITY.md) para el detalle de los controles OWASP implementados.
