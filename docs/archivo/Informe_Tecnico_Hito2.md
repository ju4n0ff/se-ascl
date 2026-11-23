# SignIA — Informe Técnico Hito 2

**Proyecto:** Traductor de Lengua de Señas Chilena  
**Asignatura:** INGT1003 — Arquitectura de Desarrollo (Móvil y Web)  
**Equipo:** Concha J., Urbina L., Vega J.  
**Fecha:** Noviembre 2026

---

## 1. Introducción

Este informe documenta la implementación del motor backend del sistema SignIA, cumpliendo con los requisitos del Hito 2: servicio del lado del servidor funcionando, interfaz de programación diseñada, capas separadas, datos que persisten y decisiones de arquitectura defendidas.

El sistema traduce Lengua de Señas Chilena (LSCh) a texto y audio en tiempo real. En el Hito 1 se propuso una arquitectura híbrida: extracción de landmarks en el cliente e inferencia en el servidor. Este hito construye ese servidor.

---

## 2. Cambios respecto del Hito 1

### 2.1 Decisiones que se mantuvieron

| Decisión | Hito 1 | Hito 2 | Estado |
|----------|--------|--------|--------|
| Python + FastAPI para backend | Propuesto | Implementado | ✅ Confirmada |
| PostgreSQL para persistencia | Propuesto | Implementado | ✅ Confirmada |
| SVM para señas estáticas | Propuesto | Capa de inferencia lista | ✅ Pendiente entrenamiento |
| LSTM para señas dinámicas | Propuesto | Capa de inferencia lista | ✅ Pendiente entrenamiento |
| Cliente envía landmarks, no video | Propuesto | Contrato API definido | ✅ Implementado |

### 2.2 Decisiones que cambiaron

| Aspecto | Hito 1 | Hito 2 | Motivo |
|---------|--------|--------|--------|
| **Protocolo de comunicación** | HTTP REST | **WebSocket + REST** | El profesor indicó que WebSocket es más adecuado para comunicación en tiempo real con landmarks que llegan a 30 FPS |
| **Almacenamiento de landmarks** | No especificado | **No se almacenan** | Solo se almacena el resultado (texto predicho, confianza, timestamp). Los landmarks son efímeros |
| **Datos biométricos** | Cara mencionada como sensible | **Cara no se procesa en backend** | El cliente extrae face landmarks pero no los envía al servidor. Cumple con control de ciberseguridad |
| **Cuenta de usuario** | No especificada | **JWT + historial por usuario** | Necesario para persistir el historial de sesiones |

### 2.3 Lo que no cambió

- El pipeline de 3 etapas (landmarks → clasificación → NLP) se mantiene
- La separación cliente-servidor con capas definidas
- La decisión de modelo ligero (~10 MB vs cientos de MB)

---

## 3. Arquitectura del Backend

### 3.1 Estructura en capas

```
backend/
├── app/
│   ├── main.py              → Punto de entrada FastAPI, CORS, lifespan
│   ├── config.py            → Configuración desde .env (pydantic-settings)
│   ├── routes/              → Capa de presentación (endpoints)
│   │   ├── auth.py          → Registro y login (JWT)
│   │   ├── recognition.py   → Reconocimiento REST
│   │   ├── history.py       → CRUD de historial
│   │   └── ws.py            → WebSocket tiempo real
│   ├── services/            → Capa de lógica de negocio
│   │   └── inference.py     → Carga de modelos SVM/LSTM + predicción
│   ├── models/              → Capa de acceso a datos
│   │   ├── database.py      → Conexión SQLAlchemy async
│   │   └── entities.py      → Entidades User, HistoryEntry
│   └── schemas/             → Contratos Pydantic (request/response)
│       └── schemas.py
├── db/
│   ├── schema.sql           → Script de creación PostgreSQL
│   └── seed.sql             → Datos de prueba ficticios
├── requirements.txt
├── .env.example
└── README.md
```

### 3.2 Responsabilidades por capa

| Capa | Responsabilidad | Archivos |
|------|-----------------|----------|
| **Presentación** | Recibir peticiones, validar formato, devolver respuestas HTTP | `routes/*.py` |
| **Lógica de negocio** | Cargar modelos, ejecutar inferencia, mapear gloss→español | `services/inference.py` |
| **Datos** | Consultas SQL, transacciones, persistencia | `models/entities.py`, `database.py` |
| **Contratos** | Definir estructura de datos de entrada/salida | `schemas/schemas.py` |

**Regla aplicada:** El controlador no contiene lógica de negocio, y las consultas SQL viven solo en la capa de datos.

---

## 4. Recorrido de una petición (caso de uso)

**Caso: "Detectar la seña HOLA en modo dinámico"**

1. **Cliente** — El navegador detecta movimiento significativo en las manos (GestureSegmenter) y envía los landmarks por WebSocket:
   ```json
   {"mode": "dynamic", "hands": [{"landmarks": [...21 puntos...], "handedness": "Right"}]}
   ```

2. **WebSocket (routes/ws.py)** — Recibe el JSON, valida `mode` y `hands`, llama al servicio de inferencia.

3. **Servicio de inferencia (services/inference.py)** — Aplana los landmarks a un vector de 126 features (21 puntos × 3 coordenadas × 2 manos), carga el modelo LSTM y ejecuta `predict()`.

4. **Modelo LSTM** — Devuelve la clase predicha con su confianza. El servicio mapea el gloss "HOLA" a "¡Hola!" usando el diccionario NLP.

5. **Respuesta** — El servidor envía de vuelta:
   ```json
   {"predicted_label": "HOLA", "spanish_text": "¡Hola!", "confidence": 0.94, "mode": "dynamic"}
   ```

6. **Cliente** — React recibe el resultado, lo agrega a la transcripción y activa el TTS.

7. **Datos** — Si `session_id` fue enviado, el resultado se guarda en la tabla `history` de PostgreSQL.

---

## 5. Modelo de datos

### 5.1 Diagrama entidad-relación

```
┌─────────────────────┐       ┌─────────────────────────┐
│       users          │       │        history           │
├─────────────────────┤       ├─────────────────────────┤
│ id          SERIAL  │──┐    │ id          SERIAL      │
│ username    VARCHAR │  │    │ user_id     INT (FK)    │
│ email       VARCHAR │  └───>│ predicted_label VARCHAR │
│ password_hash VARCHAR│      │ spanish_text  TEXT      │
│ created_at  TIMESTAMPTZ    │ confidence    FLOAT      │
└─────────────────────┘      │ mode          VARCHAR    │
                              │ created_at    TIMESTAMPTZ│
                              └─────────────────────────┘
```

### 5.2 Tablas

**users** — Cuentas de usuario para persistir historial.

| Columna | Tipo | Constraints |
|---------|------|-------------|
| id | SERIAL | PRIMARY KEY |
| username | VARCHAR(50) | UNIQUE, NOT NULL, INDEX |
| email | VARCHAR(100) | UNIQUE, NOT NULL |
| password_hash | VARCHAR(255) | NOT NULL |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |

**history** — Registro de señas reconocidas.

| Columna | Tipo | Constraints |
|---------|------|-------------|
| id | SERIAL | PRIMARY KEY |
| user_id | INTEGER | FK → users.id, ON DELETE CASCADE |
| predicted_label | VARCHAR(50) | NOT NULL |
| spanish_text | TEXT | NOT NULL |
| confidence | FLOAT | NOT NULL, CHECK (0 ≤ x ≤ 1) |
| mode | VARCHAR(20) | NOT NULL, CHECK ('static','dynamic') |
| created_at | TIMESTAMPTZ | DEFAULT NOW(), INDEX DESC |

**Script de creación:** `db/schema.sql` (ejecutar desde cero).

---

## 6. Selección de tecnologías

### 6.1 Backend: Python + FastAPI (confirmado)

Comparación realizada en el Hito 1, ahora verificada en implementación:

| Criterio | Java (Spring Boot) | Python (FastAPI) | Decisión |
|----------|--------------------|--------------------|----------|
| Integración con modelos ML | Requiere JNI/PMML | Nativa (scikit-learn, TF) | Python ✅ |
| Curva de desarrollo | Media-alta | Baja | Python ✅ |
| Concurrencia | Superior (multihilo real) | Limitada por GIL | Java ✅ |

**Desventaja asumida (mantenida):** El GIL limita la concurrencia multihilo. Para el volumen esperado (pocas peticiones simultáneas de un semestre), no es un cuello de botella.

### 6.2 Base de datos: PostgreSQL (confirmado)

| Criterio | PostgreSQL | SQLite | MongoDB |
|----------|------------|--------|---------|
| Relacional con integridad | ✅ | ✅ | ❌ |
| Escalabilidad | Alta | Baja (archivo único) | Alta |
| Concurrent writes | ✅ | ❌ (bloqueo) | ✅ |
| Setup para demo | Requiere servicio | Cero config | Requiere servicio |

**Decisión:** PostgreSQL — robustez transaccional y estándar industrial. Para desarrollo local, se puede usar Docker o instalación directa.

### 6.3 WebSocket + REST (nuevo en Hito 2)

| Protocolo | Uso | Justificación |
|-----------|-----|---------------|
| **WebSocket** | Reconocimiento en tiempo real | Los landmarks llegan a ~30 FPS; HTTP agregaría latencia por overhead de conexión por cada frame |
| **REST** | Auth, historial, health check | Operaciones CRUD puntuales donde no se necesita streaming |

---

## 7. Interfaz de programación (API)

Contrato completo en: [`docs/API_Contract.md`](./API_Contract.md)

### Resumen de endpoints

| Método | Ruta | Descripción | Éxito | Errores |
|--------|------|-------------|-------|---------|
| POST | `/api/auth/register` | Registro | 201 | 409, 422 |
| POST | `/api/auth/login` | Login JWT | 200 | 401, 422 |
| POST | `/api/recognize` | Reconocimiento REST | 200 | 422 |
| GET | `/api/history/{user_id}` | Historial | 200 | 404 |
| DELETE | `/api/history/{entry_id}` | Borrar entrada | 204 | 404 |
| GET | `/api/health` | Health check | 200 | — |
| WS | `/ws/recognize` | Tiempo real | JSON | JSON error |

### Colección de pruebas

Disponible en `backend/postman_collection.json` — importable en Postman/Insomnia.

---

## 8. Manejo de errores

| Código | Condición | Respuesta |
|--------|-----------|-----------|
| 401 | Credenciales inválidas | `{"detail": "Credenciales inválidas"}` |
| 404 | Recurso no encontrado | `{"detail": "Entrada no encontrada"}` |
| 409 | Usuario duplicado | `{"detail": "Usuario o email ya existe"}` |
| 422 | Validación fallida | `{"detail": "modo inválido"}` o array de errores Pydantic |
| 500 | Error de inferencia (WS) | `{"error": "Error en inferencia"}` |

**Principio:** Un error siempre se devuelve con su código de estado correcto, nunca como 200.

---

## 9. Manejo de credenciales

- Las credenciales de PostgreSQL están en `.env` (gitignorado)
- `.env.example` contiene valores de ejemplo sin datos reales
- La contraseña del usuario se almacena con **bcrypt** (hash), nunca en texto plano
- El JWT se firma con `SECRET_KEY` definida en `.env`
- **No hay credenciales en el código fuente**

---

## 10. Seguridad y datos personales

### 10.1 Datos que trata el sistema

| Dato | Sensibilidad | ¿Se almacena? | ¿Se envía al servidor? |
|------|-------------|---------------|------------------------|
| Landmarks de manos | Baja (no identifica persona) | No | Sí (efímero) |
| **Landmarks faciales** | **Alta (biométrico)** | **No** | **No** |
| Texto predicho | Baja | Sí (historial) | Sí |
| Email/contraseña | Media | Sí (hash bcrypt) | Sí (solo registro/login) |

### 10.2 Control de ciberseguridad

- **Face landmarks no salen del cliente.** El sistema los detecta localmente (para expresiones futuras) pero no los envía al backend.
- **Video nunca se transmite.** Solo vectores de landmarks normalizados (0-1).
- **Contraseñas con bcrypt** (costo 12).
- **JWT con expiración** (60 minutos por defecto).
- **CORS restringido** a orígenes de desarrollo conocidos.

---

## 11. Limitaciones declaradas

1. **Modelos sin entrenar:** Las capas de inferencia SVM y LSTM están implementadas pero requieren un dataset de entrenamiento para producir modelos funcionales.
2. **Sin autenticación completa:** El login genera tokens pero los endpoints no validan JWT aún (pendiente para producción).
3. **Sin rate limiting:** No hay protección contra abuso de la API.
4. **Un solo modelo por modo:** No hay ensembling ni modelos específicos por usuario.
5. **Sin HTTPS:** Para producción se requiere TLS.

---

## 12. Cómo levantar el servicio

```bash
# 1. Instalar dependencias
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# 2. Configurar
copy .env.example .env
# Editar .env con credenciales de PostgreSQL

# 3. Crear base de datos
createdb signia
psql -U user -d signia -f db/schema.sql
psql -U user -d signia -f db/seed.sql  # datos de prueba

# 4. Levantar
uvicorn app.main:app --reload --port 8000
# Documentación: http://localhost:8000/docs
```

**Verificación:** `GET http://localhost:8000/api/health` debe responder `{"status": "ok"}`.

---

## 13. Conclusiones

Se construyó el motor backend completo según lo propuesto en el Hito 1, con las siguientes verificaciones:

- ✅ Servicio FastAPI levantando y respondiendo health check
- ✅ API REST con 6 endpoints documentados
- ✅ WebSocket para comunicación en tiempo real
- ✅ PostgreSQL con script de creación reproducible
- ✅ Capas separadas (routes → services → models)
- ✅ Credenciales fuera del repositorio (.env.example)
- ✅ Errores con códigos de estado correctos
- ✅ Frontend conectado al backend por WebSocket

**Pendiente para Hito 3:** Entrenar los modelos con el dataset de señas, validar el flujo completo de punta a punta, y documentar la evolución desde este hito.

---

## Bibliografía

- FastAPI. (2026). *FastAPI Documentation*. https://fastapi.tiangolo.com/
- PostgreSQL Global Development Group. (2026). *About PostgreSQL*. https://www.postgresql.org/about/
- Scikit-learn developers. (2026). *Support Vector Machines*. https://scikit-learn.org/stable/modules/svm.html
- Keras Team. (2026). *Timeseries forecasting*. https://keras.io/examples/timeseries/
- Mozilla. (2026). *WebSocket API*. MDN Web Docs.
- Python Software Foundation. (2026). *The Global Interpreter Lock*. https://docs.python.org/3/c-api/threads.html
