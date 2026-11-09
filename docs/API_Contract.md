# SignIA — Contrato de la Interfaz de Programación (API)

**Versión:** 1.0  
**Fecha:** 2026  
**Base URL:** `http://localhost:8000`

---

## 1. Autenticación

### POST /api/auth/register

Crea un nuevo usuario.

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `username` | string | Sí | Nombre de usuario (único, 3-50 chars) |
| `email` | string | Sí | Email válido (único) |
| `password` | string | Sí | Contraseña (mínimo 6 chars) |

**Éxito — 201 Created:**
```json
{
  "id": 1,
  "username": "test_user",
  "email": "test@signia.cl"
}
```

**Error — 409 Conflict:**
```json
{ "detail": "Usuario o email ya existe" }
```

**Error — 422 Validation Error:**
```json
{ "detail": [{"loc": ["body", "username"], "msg": "Field required"}] }
```

---

### POST /api/auth/login

Autentica y devuelve un token JWT.

| Campo | Tipo | Requerido |
|-------|------|-----------|
| `username` | string | Sí |
| `password` | string | Sí |

**Éxito — 200 OK:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

**Error — 401 Unauthorized:**
```json
{ "detail": "Credenciales inválidas" }
```

---

## 2. Reconocimiento

### POST /api/recognize

Recibe landmarks de manos y devuelve la seña clasificada.

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `mode` | string | Sí | `"static"` (deletreo) o `"dynamic"` (conversación) |
| `hands` | array | Sí | 1-2 manos con landmarks de 21 puntos |
| `hands[].landmarks` | array | Sí | 21 puntos `{x, y, z}` (float, normalizados 0-1) |
| `hands[].handedness` | string | Sí | `"Left"` o `"Right"` |
| `face` | object | No | Landmarks faciales (solo envío, no se almacena) |
| `session_id` | integer | No | ID de usuario para guardar en historial |

**Éxito — 200 OK:**
```json
{
  "predicted_label": "HOLA",
  "spanish_text": "¡Hola!",
  "confidence": 0.94,
  "mode": "dynamic",
  "timestamp": "2026-11-06T15:30:00Z"
}
```

**Error — 422 Validation Error:**
```json
{ "detail": "mode debe ser 'static' o 'dynamic'" }
```
```json
{ "detail": "Se requiere al menos una mano" }
```

---

### WS /ws/recognize

WebSocket para reconocimiento en tiempo real.

**Cliente envía:**
```json
{
  "mode": "dynamic",
  "hands": [
    {
      "landmarks": [{"x": 0.5, "y": 0.3, "z": 0.1}, ...],
      "handedness": "Right"
    }
  ]
}
```

**Servidor responde:**
```json
{
  "predicted_label": "GRACIAS",
  "spanish_text": "Gracias",
  "confidence": 0.87,
  "mode": "dynamic"
}
```

**Error:**
```json
{ "error": "JSON inválido" }
```
```json
{ "error": "mode debe ser 'static' o 'dynamic'" }
```
```json
{ "error": "Se requiere al menos una mano" }
```
```json
{ "error": "Error en inferencia" }
```

---

## 3. Historial

### GET /api/history/{user_id}

Obtiene el historial de reconocimientos de un usuario.

**Parámetros de query:**

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `limit` | integer | 50 | Máximo 200 entradas |

**Éxito — 200 OK:**
```json
[
  {
    "id": 1,
    "user_id": 1,
    "predicted_label": "HOLA",
    "spanish_text": "¡Hola!",
    "confidence": 0.94,
    "mode": "dynamic",
    "created_at": "2026-11-06T15:30:00Z"
  }
]
```

**Error — 404 Not Found:**
```json
{ "detail": "Usuario no encontrado" }
```

---

### DELETE /api/history/{entry_id}

Elimina una entrada del historial.

**Éxito — 204 No Content** (sin body)

**Error — 404 Not Found:**
```json
{ "detail": "Entrada no encontrada" }
```

---

## 4. Salud

### GET /api/health

Verifica que el servicio esté activo.

**Éxito — 200 OK:**
```json
{ "status": "ok", "service": "signia-backend" }
```

---

## Tabla resumen de recursos

| Método | Ruta | Descripción | Éxito | Errores |
|--------|------|-------------|-------|---------|
| POST | `/api/auth/register` | Registro | 201 | 409, 422 |
| POST | `/api/auth/login` | Login | 200 | 401, 422 |
| POST | `/api/recognize` | Reconocimiento REST | 200 | 422 |
| GET | `/api/history/{user_id}` | Historial | 200 | 404 |
| DELETE | `/api/history/{entry_id}` | Borrar entrada | 204 | 404 |
| GET | `/api/health` | Health check | 200 | — |
| WS | `/ws/recognize` | Reconocimiento tiempo real | JSON | JSON error |

---

## Códigos de estado utilizados

| Código | Uso |
|--------|-----|
| 200 | Éxito (GET, POST con respuesta) |
| 201 | Recurso creado (registro) |
| 204 | Éxito sin contenido (DELETE) |
| 401 | No autenticado / credenciales inválidas |
| 404 | Recurso no encontrado |
| 409 | Conflicto (duplicado) |
| 422 | Error de validación |
