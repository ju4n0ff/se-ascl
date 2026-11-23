---
name: fastapi-lsch-backend
description: Arquitectura limpia en FastAPI, integración del modelo LSCh v3 (.keras + features_lsch.py), inferencia asíncrona no bloqueante, PostgreSQL/SQLAlchemy e infraestructura cloud (Supabase, Render, contrato con Angular en Vercel). Usar al crear, refactorizar o integrar endpoints HTTP/WebSocket y servicios de ML en backend/, o al tocar conexión a base de datos, despliegue o variables de entorno.
---

# Skill: Backend FastAPI + Integración Modelo LSCh v3

## 1. Arquitectura por Capas
Mantener separación estricta dentro de `backend/app/`:
- `core/`: `config.py` (`pydantic-settings` con validación estricta), `security.py` (hashing, JWT, dependencias de usuario), `exceptions.py` (manejadores globales de errores sin stack traces), `logging.py` (logs estructurados JSON).
- `db/`: sesión asíncrona (`asyncpg`), modelos SQLAlchemy alineados 1:1 con `backend/db/schema.sql`.
- `schemas/`: modelos Pydantic v2 con validación estricta de tipos, rangos y longitudes.
- `ml/`: `predictor.py` (`LSChPredictor`) y uso directo/sincronizado de `features_lsch.py` sin reescribir su matemática.
- `services/`: lógica de negocio (autenticación, historial, sesiones WebSocket con máquina de estados).
- `routes/`: routers delgados (solo HTTP/WS, inyección de dependencias y delegación a servicios).

## 2. Integración Exacta del Modelo v3 (`mejor_modelo_lsch.keras`)
- Cargar el modelo **una sola vez** en el `lifespan` de FastAPI y exponerlo en `app.state.predictor`.
- Validar obligatoriamente `features_lsch.verificar_config(config_path)` antes de aceptar tráfico.
- Cargar con `tf.keras.models.load_model(modelo_path, compile=False)` y correr warm-up `model(np.zeros((1, 30, 576), dtype=np.float32), training=False)`.
- **Modo `dynamic`:** usar `LSChPredictor` (89 clases, umbral `0.55`).
- **Modo `static`:** si `static_svm.joblib` no existe en disco, degradar con elegancia (registrar warning y reportarlo en `/api/health`) sin impedir que el servidor arranque para `dynamic`.
- Ejecutar `predecir_secuencia()` dentro de `await asyncio.to_thread(...)` para no bloquear el event loop de Uvicorn.

## 3. Contratos de API y Compatibilidad
- **REST `POST /api/recognize`:**
  - Aceptar secuencias `(N, 1629)` con `12 <= N <= 600` (y opción binaria `application/octet-stream` con `Float32Array` si se solicita).
  - Responder incluyendo tanto el contrato v3 (`aceptada`, `prediccion` con `clase_raw`/`texto`/`es_pregunta`/`confianza`, `top_k`, `frames_recibidos`, `latencia_ms`) como los campos compatibles con la tabla `history` (`predicted_label`, `spanish_text`, `confidence`, `mode`).
  - Si la petición incluye usuario autenticado y `aceptada == True` (y `save_history=True`), persistir el registro en `history`.
- **WebSocket `WS /ws/recognize`:**
  - Soportar streaming frame a frame de vectores de `1629` floats (JSON `{"type": "frame", "data": [...]}` y binario `Float32Array` de 6516 bytes), comandos `config`, `manual_start`, `manual_stop`, `reset`.
  - Implementar la máquina de estados calibrada en `test_local.py`: inicio tras 3 frames con mano activa (conservándolos), corte tras 10 frames sin manos o límite de 90 frames (600 en manual), descartar si `< 12` frames útiles.
  - Estado de sesión aislado por conexión (nunca compartir buffers globales entre clientes).
- **Metadatos y salud:**
  - `GET /api/health`: verificar conectividad real a PostgreSQL (`SELECT 1`), estado de carga del modelo v3, `num_clases` (`89`) y versión de features (`3`).
  - `GET /api/clases`: retornar el glosario formateado de las 89 señas soportadas.

## 4. Base de Datos y Esquema
- Asegurar consistencia exacta entre `backend/db/schema.sql`, `backend/db/seed.sql` y los modelos SQLAlchemy (incluyendo `created_at TIMESTAMPTZ DEFAULT NOW()` en `users` y `history`).
- Usar exclusivamente consultas parametrizadas vía SQLAlchemy ORM/Core. Nunca interpolar SQL con f-strings.
- Usar `pool_pre_ping=True` en el engine asíncrono para tolerar reinicios de PostgreSQL.

- Las consultas viven solo en `app/db/repositories.py` (un test AST lo exige en `app/routes/`).

## 5. Conexión a Supabase
- Usar siempre el **Pooler** (`*.pooler.supabase.com`): es IPv4 y Render no tiene salida IPv6. La conexión directa (`db.<ref>.supabase.co`) es IPv6. Usuario: `postgres.<ref>`. Copiar el host del dashboard (el índice `aws-N` no se deduce de la región).
- `DATABASE_URL` se normaliza en `core/db_url.py`: acepta `postgres://` y `postgresql://`, y retira `sslmode`, `pgbouncer`, `connection_limit` y `channel_binding`. **Nunca** depender de `?sslmode=require` crudo: asyncpg lo rechaza como kwarg.
- SSL por `connect_args` (`DB_SSL`): vacío = automático (Supabase o `sslmode=require`); explícito siempre gana. `require` cifra pero no autentica; con `DB_SSL_ROOT_CERT` (CA de Supabase) se verifica cadena y hostname. `sslmode=verify-*` nunca se degrada a `require`.
- `DB_USE_PGBOUNCER` (automático en `*.pooler.supabase.com` o puerto `6543`, modo Transaction) exige los tres: `statement_cache_size=0`, `prepared_statement_cache_size=0` y `prepared_statement_name_func` único. Sin el último, SQLAlchemy usa nombres secuenciales que reinician con cada proceso y chocan en el pooler.
- Motor: `pool_pre_ping=True`, `pool_recycle=300` (`DB_POOL_RECYCLE_S`), `DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=5`, `echo=False`. Se arma solo en `db/session.py:opciones_motor()`.
- En modo Transaction no usar `SET` de sesión, advisory locks de sesión, `LISTEN/NOTIFY` ni tablas temporales.

## 6. Despliegue en Render
- `render.yaml` en la raíz, `rootDir: backend`, `PYTHON_VERSION=3.11.x` (versión completa; `.python-version` en la raíz es solo respaldo).
- Arranque: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --ws-max-size 49152 --no-proxy-headers --no-server-header`. `--no-proxy-headers` es obligatorio (ver skill de AppSec).
- `WEB_CONCURRENCY=1` fijo: Render lo inyecta según el plan y uvicorn lo usa como número de workers; el modelo, el rate limiter y los contadores WS son por proceso.
- `requirements.txt` usa marcadores: `tensorflow-cpu==2.16.2` en Linux x86_64 y `tensorflow==2.16.2` en el resto. Ambos con `keras==3.15.1` y `numpy==1.26.4`; no cambiar uno sin correr los tests de paridad.
- RAM: `TF_CPP_MIN_LOG_LEVEL=2`, `OMP_NUM_THREADS=1`, `TF_NUM_INTRAOP_THREADS=1`, `TF_NUM_INTEROP_THREADS=1`, `MAX_CONCURRENT_INFERENCES=1`, `MAX_CONCURRENT_HASHES=1`. Nunca bajar Argon2id (m=64 MiB): se acota la concurrencia. Todo hash pasa por `security._en_pool_hash`.
- Variables nuevas: declararlas en `Settings` (con default local), `backend/.env.example`, `.env.example`, `render.yaml` si aplica y `ENV_TESTS` de `conftest.py`.

## 7. Contrato con Angular en Vercel
- `ALLOWED_ORIGINS`: lista blanca separada por comas (local + dominios `https://` de Vercel), compartida por CORS y por el `Origin` del WebSocket.
- `wss://` sin JWT en la URL: se envía `{"type": "auth", "token": ...}` como primer mensaje. CORS sin credenciales (JWT en `Authorization`).
- El cliente envía `[x, y * (alto / ancho), z]`, bloques ausentes en `0.0` y nunca espeja landmarks (espejo solo por CSS).
- Rutas sin barra final: con `DEBUG=false` no hay redirección 307.

## Checklist antes de finalizar
1. El servidor arranca limpio con `uvicorn app.main:app` y `/api/health` confirma DB `ok` y modelo v3 `loaded`.
2. Ninguna llamada a TensorFlow/NumPy corre directamente en una coroutine `async def` sin `asyncio.to_thread()`.
3. No queda ninguna referencia activa a `model.predict()` ni a `dynamic_lstm.h5`.
4. El entorno local sigue sin SSL ni ajustes de pooler (`connect_args == {}`) y `render.yaml` produce `Settings` válidos.
