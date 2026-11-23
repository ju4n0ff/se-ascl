# SeñaCL — Reglas Globales del Proyecto

Proyecto: Traductor en tiempo real de Lengua de Señas Chilena (LSCh) con **FastAPI + PostgreSQL** (`backend/`), modelo ML v3 (`conversor/`) y cliente **Angular** (`frontend/`).

## Arquitectura cloud
| Capa | Local | Nube |
|---|---|---|
| Frontend Angular (extrae landmarks con MediaPipe) | `http://localhost:4200` | **Vercel** (`https://`) |
| API FastAPI + TensorFlow CPU | `127.0.0.1:8000` | **Render** (`render.yaml`, Linux x86_64, Python 3.11, HTTPS/WSS) |
| PostgreSQL | WSL: `signia` (dev) y `signia_test` (pytest) | **Supabase** vía Pooler IPv4 + RLS |

Todo se configura por variables de entorno: el mismo código corre en local y en la nube. Los defaults
de `Settings` son los locales (sin SSL, sin PgBouncer, `TRUST_PROXY_HOPS=0`).

## Documentos Fuente de Verdad (leer antes de modificar código)
1. `README_ML.md` — Especificación exacta del modelo v3 (`mejor_modelo_lsch.keras`), geometría, preprocesamiento y contratos de inferencia.
2. `backend/README.md` — Endpoints actuales, variables de entorno, base de datos (`signia`) y despliegue (Supabase + Render + Vercel).
3. `backend/SECURITY.md` — Controles OWASP vigentes y limitaciones conocidas.
4. `frontend/README.md` — Instalación, decisiones (MediaPipe, sesión) y despliegue en Vercel.

## Skills del proyecto (`.claude/skills/`)
- `fastapi-lsch-backend` — arquitectura, modelo v3 e **infraestructura cloud** (Supabase, Render, contrato Angular).
- `appsec-owasp-hardening` — controles OWASP, **RLS, proxy inverso y CORS/CSWSH en la nube**.
- `qa-testing-parity` — paridad ML, tests de abuso, **tests cloud** y quality gates.
- `angular-mediapipe-frontend` — capas de Angular, landmarks en el navegador, WebSocket, sesión y **Vercel**.

## Invariantes Críticas del Modelo ML v3 (PROHIBIDO ROMPER)
- **Artefactos oficiales:** `conversor/modelos/mejor_modelo_lsch.keras`, `etiquetas_lsch.json`, `config_features.json` y `conversor/features_lsch.py`. No usar el legado `dynamic_lstm.h5`.
- **Geometría estricta:** cada frame contiene exactamente **1629 floats (`float32`)** en orden: Pose (99) + Rostro (1404, `refine_face_landmarks=False`) + Mano Izq (63) + Mano Der (63). Bloques ausentes = `0.0` exacto.
- **Coordenada `y` isotrópica:** `y * (alto / ancho)` solo en `y` (nunca en `x` ni `z`).
- **Prohibido espejar landmarks:** nunca invertir horizontalmente los datos que entran al modelo.
- **Remuestreo temporal exacto a 30 frames:** `N >= 30` con `np.linspace(0, N - 1, 30).round().astype(int)`; `N < 30` con zero-padding al final.
- **Inferencia segura en servidor:** validar `config_features.json` al arranque, cargar `.keras` una sola vez en `lifespan` con `compile=False`, ejecutar *warm-up* con ceros, invocar `model(x, training=False)` (NUNCA `model.predict()`) y ejecutar NumPy/TensorFlow fuera del event loop con `asyncio.to_thread()`.

## Reglas de Ingeniería y Seguridad
- Nunca commitear `.env`, secretos reales (incluye `DATABASE_URL`, contraseñas y `service_role` de Supabase), `venv/` ni artefactos temporales.
- Toda modificación al backend debe pasar por la checklist de `.claude/skills/appsec-owasp-hardening/SKILL.md`.
- Toda funcionalidad nueva o modificada requiere tests en `pytest` y validación estática (`ruff`, `bandit`) antes de declararse terminada.
- **`pytest` corre solo contra `signia_test` local.** Nunca apuntar `TEST_DATABASE_URL` a Supabase: la suite trunca tablas (`conftest.py` aborta si la base no termina en `_test` o el servidor no es local).
- `backend/db/schema.sql` hace `DROP TABLE`: en Supabase se ejecuta solo al crear el proyecto, seguido de `backend/db/supabase_rls.sql`.
- Las consultas viven solo en `app/db/repositories.py`. La IP del cliente se obtiene solo con `core/network.py:obtener_ip_cliente()` y los orígenes se validan solo con `Settings.origen_en_lista_blanca()`.
- **Frontend:** las vistas de `frontend/src/app/features/` no importan `HttpClient` ni contienen lógica de negocio. El vector de 1629 floats se arma solo en `services/landmarks.ts`; `@mediapipe/holistic` va con versión exacta y `selfieMode: false`. Toda modificación pasa por `npm test` y `npm run build`.
- Mantener la tabla `history` y los endpoints `/api/auth/*`, `/api/recognize`, `/api/history/*`, `/api/health` y `/ws/recognize` coherentes entre `backend/db/schema.sql`, los modelos SQLAlchemy y los esquemas Pydantic.

## Comandos
```powershell
# Desarrollo (desde backend/)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --ws-max-size 49152 --no-proxy-headers
# Quality gates (desde la raíz)
ruff check backend/app backend/tests
bandit -r backend/app -ll
pytest backend/tests -v
# Frontend (desde frontend/, Node >= 24)
npm install
npm start              # http://localhost:4200
npm test               # reglas de arquitectura + pruebas unitarias
npm run typecheck
npm run build
# Supabase (una vez por proyecto; URL del pooler, nunca en el repo)
psql "<URL>" -1 -v ON_ERROR_STOP=1 -f backend/db/schema.sql
psql "<URL>" -1 -v ON_ERROR_STOP=1 -f backend/db/supabase_rls.sql
```
Render despliega con `render.yaml` (Blueprint) en cada push a la rama conectada. No quitar
`--no-proxy-headers` ni `WEB_CONCURRENCY=1` de ese archivo (ver skill de AppSec).
