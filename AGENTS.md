# AGENTS.md — SeñaCL

Fuentes de verdad: `README_ML.md`, `backend/README.md`, `backend/SECURITY.md`, `frontend/README.md`, `CLAUDE.md` y `.claude/skills/`. Si un doc contradice un script, manda el script.

## Mapa activo (evitar legado)

- Producto actual: `backend/` (FastAPI + PostgreSQL), `frontend/` (Angular 22) y modelo LSCh v3 en `conversor/`. Las copias desplegadas son `backend/app/ml/features_lsch.py` y `backend/models/*`.
- `packages/`, `apps/`, `ml/` y los scripts pnpm/turbo de la raíz son del prototipo anterior: no usar `TemporalModel.ts`/GRU ni `apps/web-demo` (no existe, aunque `pnpm-workspace.yaml` lo referencia).
- `CLAUDE.md` y las 4 skills de `.claude/skills/` contienen las reglas globales deBackend, AppSec, QA y frontend; leerlas antes de modificar código.

## Comandos correctos

```powershell
# Backend: Python 3.11, PostgreSQL local; copiar backend/.env.example a backend/.env
createdb signia; psql -d signia -f backend/db/schema.sql
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --ws-max-size 49152 --no-proxy-headers
```

- `DEBUG=true` habilita `/docs`; con `DEBUG=false` (default) arranque falla si `SECRET_KEY` es débil y se exigen orígenes HTTPS.
- Frontend: `cd frontend; npm install; npm start` → `http://localhost:4200` (no `127.0.0.1`; es el origen permitido). Angular 22 exige Node >= 24.15 (Node 24.8 falla).
- Gates: `ruff check backend/app backend/tests`, `bandit -r backend/app -ll`, `pytest backend/tests -v` (raíz; requiere `pip install -r backend/requirements-dev.txt`).
- `pytest` usa `TEST_DATABASE_URL=.../signia_test` y trunca tablas: `conftest.py` aborta si la base no termina en `_test` o no es local. Nunca apuntarlo a Supabase.
- `cd frontend && npm test && npm run typecheck && npm run build`; `npm test` ejecuta primero `scripts/verificar-capas.mjs`.
- No confiar en los scripts raíz: `pnpm typecheck` falla (falta `packageManager` en `package.json`), no hay config de ESLint para `pnpm lint`, y `.github/workflows/ci.yml` es obsoleto (Node 20, `npm ci` en raíz).

## Invariantes del modelo v3

- Frame = 1629 floats `float32`: Pose 99 + Rostro 1404 (`refineFaceLandmarks=false`) + Mano Izq 63 + Mano Der 63; bloque ausente = `0.0` exacto.
- Guardar cada punto como `[x, y * (alto/ancho), z]`: solo `y`. Nunca espejar landmarks; el espejo es solo CSS. En frontend, `@mediapipe/holistic` va fijado en `0.5.1675471629` con `selfieMode: false`; `tasks-vision` no reproduce el contrato.
- Remuestreo exacto a 30 frames: `np.linspace(0, N-1, 30).round()` si `N >= 30`; zero-padding al final si `N < 30`. REST/WS aceptan 12..600 frames.
- Artefactos oficiales: `conversor/modelos/mejor_modelo_lsch.keras`, `etiquetas_lsch.json`, `config_features.json` y `features_lsch.py` (89 clases). Mantener copias backend 1:1; prohibido el legado `dynamic_lstm.h5`.
- Inferencia: validar `config_features.json` al arrancar, cargar el modelo una vez en `lifespan` con `compile=False` y warm-up, usar `model(x, training=False)` (nunca `predict()`) y ejecutar NumPy/TF con `asyncio.to_thread()`.

## Límites y seguridad

- El navegador extrae landmarks y envía vectores (WS binario recomendado: 6516 bytes/frame), nunca video; no persistir video ni landmarks. JWT en mensaje `auth`, nunca en la URL.
- Backend: rutas y esquemas sin SQL; consultas solo en `app/db/repositories.py`; IP solo vía `core/network.py:obtener_ip_cliente()`; orígenes solo vía `Settings.origen_en_lista_blanca()`.
- `backend/db/schema.sql` hace `DROP TABLE`: ejecutarlo solo al crear la base; en Supabase continuar con `db/supabase_rls.sql` y no cargar `seed.sql`.
- `render.yaml`: no quitar `--no-proxy-headers` ni `WEB_CONCURRENCY=1`; `TRUST_PROXY_HOPS` debe coincidir con la infra real (procedimiento en `backend/README.md`).
- Todo cambio en backend requiere la checklist de `.claude/skills/appsec-owasp-hardening/SKILL.md` más pytest/ruff/bandit; en frontend, `npm test` y `npm run build`.

## Frontend

- `features/`, `layout/`, `shared/` no importan `HttpClient`/`ApiService`, ni abren WebSocket/MediaPipe/`getUserMedia`; lo comprueba `frontend/scripts/verificar-capas.mjs`.
- Solo `core/auth/session.service.ts` usa almacenamiento (`sessionStorage`); sin grabación de video, `innerHTML`, JWT en URL ni rutas REST con barra final.
- El vector de 1629 se arma solo en `frontend/src/app/services/landmarks.ts`.
- Antes de Vercel, reemplazar `REPLACE_WITH_RENDER_SERVICE` en `src/environments/environment.prod.ts` (dos ocurrencias); Root Directory `frontend`, salida `dist/senacl-frontend/browser`.
