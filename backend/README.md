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

Enviar:
```json
{
  "mode": "dynamic",
  "hands": [
    {"landmarks": [{"x": 0.5, "y": 0.3, "z": 0.1}, ...], "handedness": "Right"}
  ]
}
```

Recibir:
```json
{
  "predicted_label": "HOLA",
  "spanish_text": "¡Hola!",
  "confidence": 0.94,
  "mode": "dynamic"
}
```

## Modelos

- **Static (SVM):** `models/static_svm.joblib` — clasificación de posturas fijas (deletreo)
- **Dynamic (LSTM):** `models/dynamic_lstm.h5` — secuencias temporales (conversación)

Entrenar con los scripts en `ml/training/`.
