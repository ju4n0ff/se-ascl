# SeñaCL — Reglas Globales del Proyecto

Proyecto: Traductor en tiempo real de Lengua de Señas Chilena (LSCh) con **FastAPI + PostgreSQL** (`backend/`), modelo ML v3 (`conversor/`) y futuro cliente **Angular** (`frontend/`).

## Documentos Fuente de Verdad (leer antes de modificar código)
1. `README_ML.md` — Especificación exacta del modelo v3 (`mejor_modelo_lsch.keras`), geometría, preprocesamiento y contratos de inferencia.
2. `backend/README.md` — Endpoints actuales, variables de entorno y base de datos (`signia`).

## Invariantes Críticas del Modelo ML v3 (PROHIBIDO ROMPER)
- **Artefactos oficiales:** `conversor/modelos/mejor_modelo_lsch.keras`, `etiquetas_lsch.json`, `config_features.json` y `conversor/features_lsch.py`. No usar el legado `dynamic_lstm.h5`.
- **Geometría estricta:** cada frame contiene exactamente **1629 floats (`float32`)** en orden: Pose (99) + Rostro (1404, `refine_face_landmarks=False`) + Mano Izq (63) + Mano Der (63). Bloques ausentes = `0.0` exacto.
- **Coordenada `y` isotrópica:** `y * (alto / ancho)` solo en `y` (nunca en `x` ni `z`).
- **Prohibido espejar landmarks:** nunca invertir horizontalmente los datos que entran al modelo.
- **Remuestreo temporal exacto a 30 frames:** `N >= 30` con `np.linspace(0, N - 1, 30).round().astype(int)`; `N < 30` con zero-padding al final.
- **Inferencia segura en servidor:** validar `config_features.json` al arranque, cargar `.keras` una sola vez en `lifespan` con `compile=False`, ejecutar *warm-up* con ceros, invocar `model(x, training=False)` (NUNCA `model.predict()`) y ejecutar NumPy/TensorFlow fuera del event loop con `asyncio.to_thread()`.

## Reglas de Ingeniería y Seguridad
- Nunca commitear `.env`, secretos reales, `venv/` ni artefactos temporales.
- Toda modificación al backend debe pasar por la checklist de `.claude/skills/appsec-owasp-hardening/SKILL.md`.
- Toda funcionalidad nueva o modificada requiere tests en `pytest` y validación estática (`ruff`, `bandit`) antes de declararse terminada.
- Mantener la tabla `history` y los endpoints `/api/auth/*`, `/api/recognize`, `/api/history/*`, `/api/health` y `/ws/recognize` coherentes entre `backend/db/schema.sql`, los modelos SQLAlchemy y los esquemas Pydantic.