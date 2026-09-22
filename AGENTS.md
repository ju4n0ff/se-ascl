# AGENTS.md

## Project

Chilean Sign Language (LSCh) interpreter: camera captures hand/face landmarks, ML classifies signs, NLP maps to Spanish text, TTS speaks it. Three targets: web (Vite+React), desktop (Tauri), mobile (React Native).

## Monorepo structure

- **`packages/`** — six `@senascl/*` internal libs, all pure TS (tsc output to `dist/`)
  - `shared-types` — canonical types, no dependencies. Everything depends on this.
  - `core-ml` — TFLite model wrapper, depends on shared-types
  - `landmarks` — MediaPipe Hand/Face Landmarker integration
  - `nlp-lsch` — LSCh→Spanish dictionary and grammar reconstruction
  - `tts` — text-to-speech abstraction (platform-specific implementations are TODO)
  - `ui-kit` — shared React components (peer dep: react 18/19)
- **`apps/web-demo`** — Vite+React demo, dev server on port 3000
- **`apps/desktop`** — Tauri wrapper around web-demo, dev on port 3001
- **`apps/mobile`** — React Native app
- **`ml/`** — Python ML pipeline (training, export, evaluation). Not part of the JS build.

## Sign Recognition Architecture (Dual-Path)

The system uses two parallel recognition paths:

**Path A — Static (Alphabet Letters):**
- Single frame → heuristic finger position classifier → letter
- Used when hand is relatively still (velocity < threshold for N frames)
- Implemented in `apps/web-demo/src/classifySigns.ts`

**Path B — Dynamic (Words/Phrases):**
- Frame sequence (30 frames) → GRU temporal model → word
- Used when significant hand movement is detected
- Pipeline: `FrameBuffer` → `GestureSegmenter` → `TemporalModel` → `SignDecider`
- All in `apps/web-demo/src/recognition/`

**Key files:**
- `FrameBuffer.ts` — Sliding window accumulating last 30 frames
- `GestureSegmenter.ts` — Velocity-based start/end detection (like VAD for hands)
- `TemporalModel.ts` — GRU implementation matching Python training exactly
- `SignDecider.ts` — Orchestrates which path to use, translates gloss→Spanish via nlp-lsch

## Dataset Situation (Important)

**No public LSCh dataset exists.** The only available LSCh data is alphabet-only (static frames), not dynamic words. Academic papers confirm: "the only available dataset is the alphabet... not at word level."

**Available alternative: LSA64 (Argentine Sign Language)**
- Public dataset with 64 signs, ~3200 video clips
- Download: https://github.com/Lenguaje-De-Senas-Argentino/LSA64
- Format: MP4 videos organized by sign class
- Can be used for: pre-training, transfer learning, architecture validation
- Cannot replace: LSCh-specific vocabulary and grammar

**Using LSA64 for development:**
```bash
# Download LSA64 dataset
git clone https://github.com/Lenguaje-De-Senas-Argentino/LSA64.git ml/datasets/LSA64

# Extract landmarks from LSA64 videos
python ml/datasets/extract_landmarks_from_videos.py \
  --input ml/datasets/LSA64 \
  --output ml/datasets/lsa64_landmarks.json

# Train temporal model on LSA64 (validate architecture works)
python ml/training/train_temporal.py \
  --dataset ml/datasets/lsa64_landmarks.json \
  --output ml/models/temporal_lsa64.json
```

**Path to LSCh-specific dataset:**
1. Use LSA64 to validate pipeline end-to-end
2. Create custom dataset using `ml/datasets/capture_dynamic_clip.py`
3. Target: 15-20 clips per word for 8-12 core LSCh signs
4. Later: expand with community-contributed data

## Commands

```bash
# From repo root (requires pnpm)
pnpm install          # install all deps
pnpm lint             # eslint across repo
pnpm typecheck        # turbo: typechecks all packages in dependency order
pnpm build            # turbo: builds all packages (shared-types first, then consumers)
pnpm test             # turbo: runs tests (currently only nlp-lsch has tests)
pnpm clean            # removes dist/ in all packages

# Single package (use turbo filter)
pnpm --filter @senascl/nlp-lsch test
pnpm --filter senascl-web-demo dev

# ML pipeline (Python, separate from JS)
# Phase 1: Dataset preparation
python ml/datasets/capture_dynamic_clip.py --output-dir ml/datasets/clips/
python ml/datasets/inspect_dataset.py --dataset-dir ml/datasets/clips/

# Phase 2: Training
python ml/training/train_temporal.py \
  --dataset-dir ml/datasets/clips/ \
  --output ml/models/temporal_weights.json

# Phase 3: Validation
python ml/export/validate_weights.py --weights ml/models/temporal_weights.json
```

## Required order

`build` depends on `^build` (upstream packages build first). Turborepo handles this automatically. For manual verification: `pnpm build && pnpm typecheck && pnpm test`.

## ML Training Pipeline (4 Phases)

**Phase 1 — Dataset:** `capture_dynamic_clip.py` records clips per word (SPACE to record, ENTER to save). Target: 15-20 clips per word for 8-12 words.

**Phase 2 — Training:** `train_temporal.py` trains GRU with architecture matching TypeScript runtime. Exports weights as JSON compatible with `TemporalModel.ts`.

**Phase 3 — NLP Connection:** Dynamic sign glosses are translated to Spanish via `lookupSign()` from `@senascl/nlp-lsch`. Dictionary in `packages/nlp-lsch/src/dictionary.ts`.

**Phase 4 — Validation:** Test each word with camera, record accuracy in a table. Compare with offline validation accuracy.

## TypeScript config

- Strict mode enabled globally in `tsconfig.base.json` (ES2022, bundler resolution)
- Path aliases for all `@senascl/*` packages defined in `tsconfig.base.json`
- `noUnusedLocals`, `noUnusedParameters`, `noImplicitReturns` — all enforced
- Each package extends the base config; web-demo uses `react-jsx`, mobile uses `react-native`

## Testing

- Only `@senascl/nlp-lsch` has tests: `node --test dist/__tests__/*.test.js`
- Tests run against compiled JS in `dist/` — must `build` first before testing
- No test framework — uses Node.js built-in test runner
- Mobile has jest in scripts but no jest config exists yet
- Web-demo has NLP connection test at `src/__tests__/nlp-connection.test.ts`

## Gotchas

- **Tauri desktop auto-builds web-demo**: `tauri.conf.json` has `beforeDevCommand`/`beforeBuildCommand` that run `pnpm --filter senascl-web-demo dev/build`. Don't manually start web-demo when using `tauri dev`.
- **Many TODOs in packages**: `core-ml`, `landmarks`, `tts` have placeholder implementations. Don't assume they're complete.
- **ML models are gitignored**: `*.tflite`, `*.onnx`, `*.pt`, `*.pth` are all excluded. The ML pipeline produces them locally.
- **No ESLint config file**: The `lint` script references eslint but no config file exists. You may need to create one or adjust the script.
- **No CI workflows**: `.github/workflows/` exists but is empty.
- **Desktop app is a Tauri shell**: It has no TypeScript source — it's purely a Rust/Tauri wrapper that loads the web-demo frontend. All UI logic lives in `apps/web-demo/src/`.
- **Mobile app is minimal**: Only `App.tsx` and `index.ts`. Core logic is in packages but not yet wired into the mobile app beyond type imports.
- **Temporal model needs real weights**: `TemporalModel.ts` initializes with random weights. Must run training pipeline to get real weights before dynamic recognition works.
- **GRU architecture must match exactly**: Python training (`train_temporal.py`) and TypeScript runtime (`TemporalModel.ts`) must have identical gate structure and weight shapes.
- **LSA64 is Argentine, not Chilean**: Signs may differ between LSA and LSCh. Use LSA64 for pipeline validation only, then create LSCh-specific dataset.
