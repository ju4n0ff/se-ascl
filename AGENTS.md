# AGENTS.md

## Project
LSCh (Chilean Sign Language) interpreter: camera landmarks -> sign classification -> Spanish text/NLP -> TTS. Targets: web (Vite+React), desktop (Tauri wrapper around web-demo), mobile (React Native, minimal).

## Repo map
- `packages/*` — `@senascl/*` TS libs built with `tsc` to `dist/`. `shared-types` is canonical; most packages depend on it.
  - `nlp-lsch` has the only real package test script. `core-ml`, `landmarks`, `tts` contain TODO/placeholder implementations.
- `apps/web-demo` — main UI/recognition app (Vite, port 3000). Static heuristic: `src/classifySigns.ts`. Dynamic pipeline: `src/recognition/{FrameBuffer,GestureSegmenter,TemporalModel,SignDecider}.ts`.
- `apps/desktop` — Tauri shell only (`src-tauri/`), no TS app source; loads web-demo.
- `apps/mobile` — minimal RN app (`src/App.tsx`, `src/index.ts`); **not** listed in `pnpm-workspace.yaml`.
- `backend/` — FastAPI + WebSocket prototype. REST/WS routes in `app/routes/`, inference in `app/services/inference.py`, DB models/schemas in `app/models`+`app/schemas`.
- `ml/` — Python dataset/training/export scripts; not part of JS build.
- `conversor/` — production LSCh v3 artifacts: `modelos/mejor_modelo_lsch.keras` (89 classes), `etiquetas_lsch.json`, `config_features.json`, and `features_lsch.py` (NumPy-only preprocessing contract). Treat this as the trained-model source of truth.

## Commands (repo root, pnpm)
- `pnpm install`
- `pnpm lint` — runs `eslint . --ext .ts,.tsx`; **no ESLint config file found**, verify before relying on it.
- `pnpm typecheck` / `pnpm build` / `pnpm test` / `pnpm clean` — Turbo tasks; build is dependency-ordered (`^build`).
- Focused: `pnpm --filter @senascl/nlp-lsch build && pnpm --filter @senascl/nlp-lsch test` (tests run `node --test dist/__tests__/*.test.js`, so build first).
- Web dev: `pnpm --filter senascl-web-demo dev`. Desktop dev: `pnpm --filter senascl-desktop dev` (Tauri `beforeDevCommand` starts web-demo; don’t start it separately).

## Backend / model integration
- Backend local run: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000` (`/docs`, `GET /api/health`, `WS /ws/recognize`).
- Backend DB is optional only for auth/history; recognition endpoints should work without DB when models are available. `db/schema.sql` is the schema source.
- LSCh v3 model contract (`conversor/README_ML.md`): raw sequence `(N,1629)` MediaPipe Holistic landmarks with isotropic `y = y * (h/w)`, resampled to 30 frames, `features_lsch.preparar_entrada_modelo` -> `(30,576)`, Keras model -> 89 softmax classes. **Never mirror frames before MediaPipe; preserve exact 1629 block order and zero-fill missing blocks.**
- Current web-demo/backend integration is simpler (hand landmarks over WS). When changing recognition contracts, update frontend payload, backend schema/service, and docs together.

## Testing / CI gotchas
- Only `@senascl/nlp-lsch` has a package `test` script. `apps/web-demo/src/__tests__/nlp-connection.test.ts` exists but is not wired into scripts/turbo.
- `apps/mobile` has `test: jest` but no Jest config found.
- `.github/workflows/ci.yml` exists but is **stale/npm-based** (`npm ci`, `npm run ...`) and does not reflect pnpm/turbo workspace reality; do not treat it as authoritative.

## Gotchas
- **Tauri is a shell**: UI logic belongs in `apps/web-demo`, not `apps/desktop`.
- **Generated/artifacts gitignored**: `dist/`, `.turbo/`, venvs, `__pycache__`, ML/data artifacts (`*.tflite`, `*.onnx`, `*.pt`, `*.pth`, `*.keras` patterns in gitignore except specific paths—check before adding model files).
- **Temporal model weights**: `TemporalModel.ts` initializes random weights until real weights are loaded. Python GRU training/export and TS runtime must keep identical architecture/weight shapes.
- **LSA64 != LSCh**: use LSA64 only for pipeline validation/pretraining; it does not replace Chilean LSCh data.
