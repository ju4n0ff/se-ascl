# SeñaCL Backend

## Requisitos

- Python 3.11+
- PostgreSQL 14+
- TensorFlow 2.16.2 + Keras 3.15.1 (modelo LSCh v3, CPU). En Linux x86_64 `requirements.txt` instala `tensorflow-cpu`.

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

(El `.env.example` de la raíz del repositorio es una copia de este mismo archivo.)

Editar `.env` con tus credenciales de PostgreSQL. Variables clave:

| Variable | Descripción |
|----------|-------------|
| `DEBUG` | `false` por defecto. Con `false`: sin `/docs`, HSTS activo, WS exige `Origin` y el arranque falla si `SECRET_KEY` es débil. |
| `SECRET_KEY` | Mínimo 32 caracteres aleatorios. Generar con `python -c "import secrets; print(secrets.token_urlsafe(64))"`. |
| `ALLOWED_ORIGINS` | Orígenes permitidos para CORS y para el `Origin` del WebSocket, separados por comas (sin `*`). Con `DEBUG=false` se exige `https://`, salvo loopback. |
| `ALLOWED_ORIGIN_REGEX` | Opcional, vacío por defecto. Patrón cerrado para previews de Vercel. |
| `DB_SSL`, `DB_USE_PGBOUNCER` | Vacío = automático según `DATABASE_URL`; `true`/`false` siempre gana. |
| `DB_SSL_ROOT_CERT` | Opcional. CA para verificar el certificado de la base (sin ella, `DB_SSL` cifra pero no autentica). |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE_S` | Pool de conexiones (5, 5, 300 s). |
| `TRUST_PROXY_HOPS` | Proxies confiables (0–5). `0` ignora `X-Forwarded-For`. |
| `MAX_CONCURRENT_INFERENCES`, `MAX_CONCURRENT_HASHES` | Topes de inferencias y de hashes Argon2id simultáneos. |
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

El diagrama entidad-relación está en [`db/modelo_datos.mmd`](db/modelo_datos.mmd) (Mermaid; se
exporta a SVG/PNG con `mmdc` o en https://mermaid.live).

## Levantar el servidor

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --ws-max-size 49152 --no-proxy-headers
```

`--no-proxy-headers` evita que uvicorn reescriba la IP con `X-Forwarded-For`; `--ws-max-size` aplica el tope de 48 KB por mensaje WebSocket también a nivel de protocolo
(`python -m app.main` ya lo configura). Documentación interactiva (solo con `DEBUG=true`):
http://localhost:8000/docs (botón **Authorize** para pegar el JWT).

## Estructura en capas

| Capa | Módulos | Responsabilidad |
|------|---------|-----------------|
| Transporte | `app/routes/`, `app/schemas/` | Validar la entrada, llamar a servicios o repositorios y traducir a códigos HTTP. **Sin consultas** |
| Negocio | `app/services/`, `app/ml/` | Reglas de persistencia, segmentación e inferencia |
| Datos | `app/db/repositories.py`, `app/db/models.py`, `app/db/session.py` | `UserRepository` y `HistoryRepository` concentran todas las consultas de la API; `get_db()` maneja la transacción |
| Transversal | `app/core/` | Configuración, seguridad, rate limiting, errores y logs |

Un test estático (`test_capas_rutas_sin_consultas_sqlalchemy`) falla si una ruta importa
`select`/`insert`/`update`/`delete`/`text` de SQLAlchemy o consulta la sesión directamente.

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/auth/register` | Registro (3/min por IP; `409` genérico si ya existe) |
| POST | `/api/auth/login` | Login JSON `{username, password}`, devuelve JWT (5/min por IP) |
| POST | `/api/recognize` | Reconocimiento de una secuencia `(N, 1629)`; JWT opcional (30/min por IP) |
| GET | `/api/users/me` | 🔒 Perfil propio: `id`, `username`, `email` (nunca `password_hash`) |
| PATCH | `/api/users/me` | 🔒 Cambia `email` y/o `new_password`; exige `current_password` (5/min por IP) |
| DELETE | `/api/users/me` | 🔒 Borra la cuenta y su historial en cascada (`204`, sin cuerpo) |
| GET | `/api/history/me` | 🔒 Historial del usuario autenticado |
| GET | `/api/history/{user_id}` | 🔒 Historial propio (`403` si `user_id` no es el del token) |
| PATCH | `/api/history/{entry_id}` | 🔒 Corrige `spanish_text` de una entrada propia (`404` si no existe o es ajena) |
| DELETE | `/api/history/{entry_id}` | 🔒 Borrar entrada propia (`404` si no existe o es ajena) |
| GET | `/api/health` | Estado de PostgreSQL y del modelo v3 (503 si está degradado) |
| GET | `/api/clases` | Glosario de las 89 señas soportadas |
| WS | `/ws/recognize` | Reconocimiento en streaming, frame a frame |

### `PATCH /api/history/{entry_id}`

```json
{ "spanish_text": "¿dónde está la salida?" }
```

- `spanish_text`: 1 a 500 caracteres tras quitar los espacios de los extremos, sin caracteres de control.
- `predicted_label`, `confidence` y `mode` son inmutables (trazabilidad del modelo): enviarlos responde `422`.
- `200` con la entrada actualizada; `404` si no existe o es de otro usuario; `401` sin token.

### `PATCH /api/users/me`

```json
{ "email": "nuevo@example.com", "new_password": "Nueva1234", "current_password": "Actual1234" }
```

- `email` y `new_password` son opcionales, pero debe venir al menos uno. `new_password` cumple la misma
  política del registro. Cualquier otro campo (`username`, `id`...) responde `422`.
- `401` genérico si `current_password` no coincide; `409` genérico si el email ya está en uso.
- Cambiar la contraseña no invalida los JWT ya emitidos (ver limitaciones en `SECURITY.md`).

### `DELETE /api/users/me`

Responde `204` y elimina la cuenta y su historial (`ON DELETE CASCADE`), sin recuperación posible. El
JWT deja de servir de inmediato (`401`). No lleva cuerpo: el cliente debe pedir confirmación.

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

## Despliegue en Supabase + Render

### 1. Supabase

1. Crear el proyecto en una región cercana a la de Render y guardar la contraseña de la base fuera del repo.
2. **Connect** → copiar la URL del **Transaction pooler** (puerto `6543`) o del **Session pooler** (`5432`).
   Ambos son IPv4. La conexión directa (`db.<ref>.supabase.co`) es IPv6 y no sirve desde Render.

   ```
   postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-[N]-[REGION].pooler.supabase.com:6543/postgres
   ```

   Copiar el host tal cual (el índice `aws-N` no se deduce de la región) y codificar los caracteres
   especiales de la contraseña (`@` = `%40`, `#` = `%23`).
3. Crear las tablas y activar RLS, en el SQL Editor o con `psql`, **en este orden**:

   ```bash
   psql "<URL del pooler>" -1 -v ON_ERROR_STOP=1 -f db/schema.sql         # ¡borra las tablas si ya existen!
   psql "<URL del pooler>" -1 -v ON_ERROR_STOP=1 -f db/supabase_rls.sql   # idempotente
   ```

   `schema.sql` empieza con `DROP TABLE`: ejecutarlo solo al crear el proyecto. Si se vuelve a
   ejecutar se pierden los datos **y** el RLS. No cargar `seed.sql` (contraseña conocida).
4. Verificar que la consulta final de `supabase_rls.sql` muestre `rls = true` en `users` e `history`, y
   que el Security Advisor no reporte tablas sin RLS. Conviene además desactivar la Data API
   (Project Settings → Data API): este proyecto no la usa.

El backend adapta la URL solo: driver `asyncpg`, SSL, y para el pooler `statement_cache_size=0`,
`prepared_statement_cache_size=0` y nombres de sentencia únicos. `DB_SSL=true` cifra sin autenticar al
servidor; para verificar el certificado, descargar la CA (Database Settings → SSL), subirla a Render
como *Secret File* y definir `DB_SSL_ROOT_CERT=/etc/secrets/prod-ca-2021.crt`.

### 2. Render

1. **New → Blueprint**, elegir el repositorio y la rama. Render lee `render.yaml` de la raíz.
2. Completar los valores pedidos: `DATABASE_URL` (pooler), `SECRET_KEY`
   (`python -c "import secrets; print(secrets.token_urlsafe(64))"`) y `ALLOWED_ORIGINS` (URL de Vercel).
3. Esperar el build y comprobar `https://<servicio>.onrender.com/api/health` → `200`, `"database": "ok"`.

El modelo `.keras` (11 MB) está en Git normal, sin LFS: se clona sin pasos extra. Con Supabase caído
`/api/health` responde `503` y Render puede reiniciar o retirar la instancia.

**`TRUST_PROXY_HOPS` (revisar tras el primer despliegue).** Es la cantidad de entradas que la
infraestructura agrega al final de `X-Forwarded-For`. El Blueprint usa `1`, el valor conservador: no es
falsificable, pero si Render agrega más saltos todos los clientes comparten un mismo cupo (5 logins/min
y 5 WebSockets **en total**). Render no documenta el número; reportes de terceros de noviembre de 2026
describen `cliente, Cloudflare, interno` (valor `3`). Para confirmarlo:

1. Hacer un intento de login desde fuera y buscar en los logs `TRUST_PROXY_HOPS=1 resuelve a una IP
   interna (X-Forwarded-For trae N entradas)`. Sin enviar esa cabecera, `N` es el número de saltos.
2. Definir `TRUST_PROXY_HOPS=N` en el dashboard y redesplegar.
3. Comprobar que no se puede evadir: 6 logins fallidos rotando `X-Forwarded-For` deben terminar en
   `429`. Y que sí separa clientes: desde otra red (datos móviles) el login responde `401`, no `429`.

Si el log no aparece, la entrada tomada ya es pública: validar igual el paso 3 (podría ser la IP de
Cloudflare y no la del cliente). Un valor mayor al real permite falsificar la IP.

**RAM.** Medido en un proceso con 1 hilo de TF y `MAX_CONCURRENT_INFERENCES=1` (Windows, TensorFlow
2.16.2; Linux con `tensorflow-cpu` puede variar y debe confirmarse en Render → Metrics):

| Situación | RAM del proceso |
|---|---|
| Modelo cargado, en reposo y con inferencias normales | ~410 MiB |
| 5 inferencias simultáneas de 600 frames | ~434 MiB (pico) |
| 10 logins simultáneos, `MAX_CONCURRENT_HASHES=1` | ~472 MiB (pico) |
| 10 logins simultáneos, `MAX_CONCURRENT_HASHES=2` | ~537 MiB (pico) |
| 10 logins simultáneos, 8 hashes a la vez | ~924 MiB (pico) |

Free y Starter (512 MB) quedan con menos de 10 % de margen: sirven para una demo. Para uso real,
**Standard (2 GB)**. Los parámetros de Argon2id (m=64 MiB) no se bajan: se limita la concurrencia. El
plan Free además suspende el servicio por inactividad y la primera petición tarda en recargar el modelo.

## Integración con Frontend Angular en Vercel

```ts
// src/environments/environment.prod.ts
export const environment = {
  production: true,
  apiUrl: 'https://senacl-api.onrender.com',
  wsUrl: 'wss://senacl-api.onrender.com/ws/recognize',
};
```

- **Orígenes:** `ALLOWED_ORIGINS=https://senacl.vercel.app,https://www.senacl.cl` (sin barra final ni
  ruta). La misma lista vale para CORS y para el `Origin` del WebSocket. Con `DEBUG=false` se rechaza
  `http://`, salvo `localhost`, `127.0.0.1` y `[::1]` (para probar la config de producción en la propia
  máquina). Al publicar el dominio definitivo, quitar los de loopback.
- **Previews (opcional):** `ALLOWED_ORIGIN_REGEX=^https://senacl-[a-z0-9-]+-miequipo\.vercel\.app$`. El
  arranque falla si el patrón es abierto. En `vercel.app` un tercero podría crear un proyecto con un
  nombre que calce: usarlo solo en pruebas, o servir los previews en un dominio propio.
- **HTTP:** `withCredentials: false`; el JWT va en `Authorization: Bearer`. Rutas sin barra final.
- **WebSocket:** `wss://` (desde una página `https://` el navegador bloquea `ws://`). El JWT nunca va en
  la URL: tras abrir, enviar `{"type": "auth", "token": "..."}`. Reconectar con espera creciente ante
  `1001` (inactividad de 60 s o redespliegue); no insistir ante `1008`.
- **Landmarks:** enviar `[x, y * (alto / ancho), z]` por punto, bloques ausentes en `0.0` exacto,
  `refineFaceLandmarks=false`. El espejo de la cámara es **solo CSS** (`transform: scaleX(-1)` en el
  `<video>`), nunca sobre los datos.
- **Cámara:** `getUserMedia` exige `https://` (Vercel lo da) o `localhost`.
- Un `500` inesperado sale sin cabeceras CORS: el navegador lo muestra como error de red (`status 0`).

## Tests y quality gates

La suite (`tests/`) corre contra la base aislada **`signia_test`** (nunca `signia`): la URL sale de
`TEST_DATABASE_URL` (por defecto `postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/signia_test`)
y la sesión se aborta si el nombre de la base no termina en `_test` o si el servidor no es local (nunca Supabase). Las tablas se truncan antes de
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
| `test_security.py` | Auth/JWT manipulados, anti-BOLA/IDOR, NaN/Inf, 413 (Content-Length y chunked), 415, 429, cabeceras, CORS, separación de capas (AST), handler 500, WebSocket (Origin, 1009, 1001, límites) |
| `test_crud.py` | CRUD de `history` y `users/me`: éxito y errores, anti-BOLA, inmutabilidad, cascada y repositorios |
| `test_auth_history.py` | Health, Argon2id, historial y reglas de persistencia de `/api/recognize` |
| `test_websocket.py` | Máquina de estados: modo auto, ruido descartado, modo manual, aislamiento y persistencia |
| `test_config_prod.py` | Validación de `Settings`, app con `DEBUG=false` (subproceso), seed idempotente |
| `test_cloud.py` | `DATABASE_URL`/SSL/pooler, IP tras el proxy, CORS y `Origin` de Vercel, RLS, `render.yaml`, guarda de base local |

## Seguridad

Ver [`SECURITY.md`](SECURITY.md) para el detalle de los controles OWASP implementados.
