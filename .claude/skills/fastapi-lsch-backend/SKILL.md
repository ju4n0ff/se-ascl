---
name: fastapi-lsch-backend
description: Arquitectura limpia en FastAPI, integración del modelo LSCh v3 (.keras + features_lsch.py), inferencia asíncrona no bloqueante y gestión de PostgreSQL/SQLAlchemy. Usar al crear, refactorizar o integrar endpoints HTTP/WebSocket y servicios de ML en backend/.
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

## Checklist antes de finalizar
1. El servidor arranca limpio con `uvicorn app.main:app` y `/api/health` confirma DB `ok` y modelo v3 `loaded`.
2. Ninguna llamada a TensorFlow/NumPy corre directamente en una coroutine `async def` sin `asyncio.to_thread()`.
3. No queda ninguna referencia activa a `model.predict()` ni a `dynamic_lstm.h5`.