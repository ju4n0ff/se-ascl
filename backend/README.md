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

```bash
copy .env.example .env       # Windows
# cp .env.example .env       # macOS/Linux
```

Editar `.env` con tus credenciales de PostgreSQL.

## Base de datos

```bash
# Crear base de datos
createdb signia

# Crear tablas
psql -U user -d signia -f db/schema.sql

# Datos de prueba (opcional)
psql -U user -d signia -f db/seed.sql
```

## Levantar el servidor

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Documentación interactiva: http://localhost:8000/docs

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/auth/register` | Registro de usuario |
| POST | `/api/auth/login` | Login, devuelve JWT |
| POST | `/api/recognize` | Reconocimiento de una secuencia `(N, 1629)` |
| GET | `/api/history/{user_id}` | Historial del usuario |
| DELETE | `/api/history/{entry_id}` | Borrar entrada |
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
| `{"type": "frame", "data": [1629 floats]}` o binario `Float32Array` (6516 bytes, little-endian) | Agrega un frame |
| `{"type": "config", "modo": "auto" \| "manual", "umbral": 0.55, "top_k": 3}` | Configura la sesión |
| `{"type": "manual_start"}` / `{"type": "manual_stop"}` | Grabación manual (tope 600 frames) |
| `{"type": "reset"}` | Vacía el buffer |

Modo automático (igual que `conversor/test_local.py`): empieza a grabar tras 3 frames seguidos con
alguna mano, corta tras 10 frames sin manos o al llegar a 90, y descarta segmentos de menos de 12 frames.

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
