# SeñaCL Backend

## Requisitos

- Python 3.11+
- PostgreSQL 14+
- (Opcional) TensorFlow para modelo LSTM dinámico

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
| POST | `/api/recognize` | Reconocimiento (REST) |
| GET | `/api/history/{user_id}` | Historial del usuario |
| DELETE | `/api/history/{entry_id}` | Borrar entrada |
| GET | `/api/health` | Health check |
| WS | `/ws/recognize` | Reconocimiento en tiempo real |

## WebSocket

Conectar a `ws://localhost:8000/ws/recognize`

### LSCh v3 (modelo entrenado, recomendado)

Enviar secuencia Holistic cruda `(N,1629)` con `y` isotrópica (`y * h/w`), sin espejar antes de MediaPipe:

```json
{
  "mode": "lsch_v3",
  "frames": [[0.1, 0.2, 0.0, "...(1629 floats total)..."]],
  "top_k": 3
}
```

Recibir:

```json
{
  "predicted_label": "hola",
  "spanish_text": "hola",
  "confidence": 0.94,
  "mode": "lsch_v3",
  "accepted": true,
  "top_k": [{"clase_raw":"hola","texto":"hola","es_pregunta":false,"confianza":0.94}],
  "frames_received": 38,
  "latency_ms": 31.2
}
```

### Legacy (simple)

`mode: "static"|"dynamic"` con `hands: [...]` sigue disponible para compatibilidad, pero LSCh v3 usa el modelo entrenado en `conversor/modelos/mejor_modelo_lsch.keras`.

## Modelos

- **LSCh v3 (producción):** `../conversor/modelos/mejor_modelo_lsch.keras` + `etiquetas_lsch.json` + `config_features.json` + `features_lsch.py`
- **Static (legacy, opcional):** `models/static_svm.joblib`
- **Dynamic (legacy, opcional):** `models/dynamic_lstm.h5`

La DB es opcional para reconocimiento; solo auth/historial la requieren.
