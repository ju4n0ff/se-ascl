# AGENTS.md — SeñaCL

Fuentes de verdad: `README_ML.md`, `backend/README.md`, `backend/SECURITY.md`, `frontend/README.md`, `CLAUDE.md` y `.claude/skills/`. Si un doc contradice un script, manda el script.

## Mapa activo (evitar legado)

- Producto actual: `backend/` (FastAPI + PostgreSQL), `frontend/` (Angular 22) y modelo LSCh v3 en `conversor/`. Las copias desplegadas son `backend/app/ml/features_lsch.py` y `backend/models/*`.
- `packages/`, `apps/`, `ml/` y los scripts pnpm/turbo de la raíz son del prototipo anterior: no usar `TemporalModel.ts`/GRU ni `apps/web-demo` (no existe, aunque `pnpm-workspace.yaml` lo referencia).
- `CLAUDE.md` y las 4 skills de `.claude/skills/` tienen las reglas de Backend, AppSec, QA y frontend; leerlas antes de modificar código.

## Comandos correctos

```powershell
# Backend: Python 3.11, PostgreSQL local; copiar backend/.env.example a backend/.env
createdb signia; createdb signia_test
psql -d signia -f backend/db/schema.sql; psql -d signia_test -f backend/db/schema.sql
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --ws-max-size 49152 --no-proxy-headers
```

- `DEBUG=true` habilita `/docs`; con `DEBUG=false` (default) arranque falla si `SECRET_KEY` es débil y se exigen orígenes HTTPS (salvo loopback).
- Frontend: `cd frontend; npm install; npm start` → `http://localhost:4200` (no `127.0.0.1`; es el origen permitido). `@angular/cli` exige Node `^22.22.3 || ^24.15.0 || >=26`; con el Node 24.8 de este entorno, ejecutar verificaciones con `npx -y node@24.15.0 node_modules/@angular/cli/bin/ng.js test --watch=false` (no cambia el Node del sistema). `ng build` queda bloqueado aquí porque la directiva de Windows bloquea `@rolldown/binding-win32-x64-msvc`.
- Gates: `ruff check backend/app backend/tests`, `bandit -r backend/app -ll`, `pytest backend/tests -v` (raíz; requiere `pip install -r backend/requirements-dev.txt`).
- `pytest` usa `TEST_DATABASE_URL=.../signia_test` y trunca tablas: `conftest.py` aborta si la base no termina en `_test` o no es local. Nunca apuntarlo a Supabase; la config de tests viene de `ENV_TESTS`, no de `backend/.env`.
- Foco: `pytest backend/tests/test_ml_parity.py -v`, `pytest backend/tests/test_security.py -k nombre -v`; en frontend, `npm run verificar` (solo reglas de capas) y `npx ng test --watch=false --include src/app/services/landmarks.spec.ts` (el builder admite `--include`/`--filter`).
- `cd frontend && npm test && npm run typecheck && npm run build`.
- No confiar en los scripts raíz: `pnpm typecheck` falla ("Could not resolve workspace: Missing `devEngines.packageManager` or legacy `packageManager`"), no hay config de ESLint para `pnpm lint`, y `.github/workflows/ci.yml` es obsoleto (Node 20, `npm ci` en raíz).

## Invariantes del modelo v3

- Frame = 1629 floats `float32`: Pose 99 + Rostro 1404 (`refineFaceLandmarks=false`) + Mano Izq 63 + Mano Der 63; bloque ausente = `0.0` exacto.
- Guardar cada punto como `[x, y * (alto/ancho), z]`: solo `y`. Nunca espejar landmarks; el espejo es solo CSS. En frontend, `@mediapipe/holistic` va fijado en `0.5.1675471629` con `selfieMode: false`; `tasks-vision` no reproduce el contrato.
- Remuestreo exacto a 30 frames: `np.linspace(0, N-1, 30).round()` si `N >= 30`; zero-padding al final si `N < 30`. REST/WS aceptan 12..600 frames.
- Artefactos oficiales: `conversor/modelos/mejor_modelo_lsch.keras`, `etiquetas_lsch.json`, `config_features.json` y `features_lsch.py` (89 clases). Mantener copias backend 1:1; prohibido el legado `dynamic_lstm.h5`.
- Los tests de paridad comparan SHA-256 de bytes: `.gitattributes` fuerza LF en los 6 archivos copiados. Si fallan en Windows con `git status` limpio, revisar CRLF en `conversor/` (aquí estaban en CRLF) y restaurar esos archivos con `git checkout -- <rutas>` antes de pytest.
- Inferencia: validar `config_features.json` al arrancar, cargar el modelo una vez en `lifespan` con `compile=False` y warm-up, usar `model(x, training=False)` (nunca `predict()`) y ejecutar NumPy/TF con `asyncio.to_thread()`.

## Límites y seguridad

- El navegador extrae landmarks y envía vectores (WS binario recomendado: 6516 bytes/frame), nunca video; no persistir video ni landmarks. JWT en mensaje `auth`, nunca en la URL.
- Backend: rutas y esquemas sin SQL; consultas solo en `app/db/repositories.py`; IP solo vía `core/network.py:obtener_ip_cliente()`; orígenes solo vía `Settings.origen_en_lista_blanca()`.
- `backend/db/schema.sql` hace `DROP TABLE`: ejecutarlo solo al crear la base; en Supabase continuar con `db/supabase_rls.sql` y no cargar `seed.sql`.
- `render.yaml`: no quitar `--no-proxy-headers` ni `WEB_CONCURRENCY=1`; `TRUST_PROXY_HOPS` debe coincidir con la infra real (procedimiento en `backend/README.md`).
- Toda variable nueva de `Settings` se declara también en `backend/.env.example`, `.env.example`, `render.yaml` y `ENV_TESTS` de `conftest.py`.
- Todo cambio en backend requiere la checklist de `.claude/skills/appsec-owasp-hardening/SKILL.md` más pytest/ruff/bandit; en frontend, `npm test` y `npm run build`.

## Frontend

- Paleta actual: azul bandera (`#174A78`) como primario/enlaces, rojo bandera (`#C8413A`) en grabación/errores, blanco nieve y arena/piel para manos; el modo oscuro conserva los mismos roles con valores más claros.
- `features/`, `layout/`, `shared/` no importan `HttpClient`/`ApiService`, ni abren WebSocket/MediaPipe/`getUserMedia`; lo comprueba `frontend/scripts/verificar-capas.mjs`.
- Solo `core/auth/session.service.ts` usa almacenamiento: JWT en `sessionStorage`, preferencias de accesibilidad en `localStorage` (`senacl.preferencias`). `core/ui/preferencias-accesibilidad.service.ts` solo aplica atributos al `<html>` y delega el guardado; `shared/panel-accesibilidad.ts` se abre desde el header o con Alt+A. Sin grabación de video, `innerHTML`, JWT en URL ni rutas REST con barra final.
- Ambos `environment*.ts` declaran `referenciasHabilitadas: false`: `services/referencia-sena.service.ts:obtenerReferenciaSena()` entrega la ilustración local `public/referencias/mano.svg` hasta que el backend exponga `GET /api/referencias/{clase}`.
- El vector de 1629 se arma solo en `frontend/src/app/services/landmarks.ts`. Si cambia la versión de MediaPipe, actualizar juntos `package.json`, `angular.json` (assets) y `RUTA_MEDIAPIPE` en `mediapipe.service.ts`.
- `environment.prod.ts` ya apunta a `https://se-ascl.onrender.com` (no queda el marcador `REPLACE_WITH_RENDER_SERVICE` que menciona el README): verificar que coincida con el servicio Render y con `ALLOWED_ORIGINS` antes de publicar en Vercel; Root Directory `frontend`, salida `dist/senacl-frontend/browser`.
