# AGENTS.md

Project guide for AI coding agents (and humans) working in this repository.

Human contributor workflow (git, PR etiquette, conventional commits) lives in
[`doc/developing_rules.md`](doc/developing_rules.md) / [`doc/developing_rules_cn.md`](doc/developing_rules_cn.md).
Product vision and gap-detection strategy live in [`doc/instruction.md`](doc/instruction.md).
This file is the **operational map of the codebase as it exists today**.

---

## What this project is

**yolo-retail-ai-agent** — shelf inventory audit system:

1. **Vision** detects `product` vs `gap` on shelves (not thousands of SKU classes).
2. **Agent** reasons over detections (and, later, planogram) to flag phantom inventory / restock actions.
3. **UI** lets staff stream cameras, run audits, chat, and browse records.

Core design choice: **binary gap detection + planogram coordinates**, not multi-SKU classification.
See `doc/instruction.md` for the product rationale.

---

## Repository layout

```text
.
├── AGENTS.md                 # this file
├── README.md                 # human quick start
├── doc/                      # product + contributor docs
├── frontend/                 # React + Vite + TypeScript UI (:5173)
├── agent/                    # FastAPI retail agent API (:8000)
├── model-local/              # local YOLO/ONNX vision service (:8001)
├── train/                    # train / validate / predict / export
├── dataset/                  # Roboflow download helpers only
└── train/export/             # runtime local weights (ONNX)
```

Each Python package is a **standalone uv project** (`pyproject.toml` + `uv.lock` + `.python-version`).
Frontend is **npm**.

---

## Runtime architecture (canonical)

```text
Browser UI  (:5173)
  │
  ├─ Camera stream / detect ──────────────► model-local (:8001)
  │                                            │
  │                                            ▼
  │                                    train/export/*.onnx
  │                                    (local weights only)
  │
  └─ Chat / database / audit narrative ──► agent (:8000)
                                              │
                                              └─ image audits ──► model-local (:8001)
```

| Port | Process | Role |
| --- | --- | --- |
| 5173 | `frontend` (Vite) | Workspace UI |
| 8000 | `agent` (FastAPI) | LLM chat, audit narratives, in-memory records |
| 8001 | `model-local` (`stream_server.py`) | **Only** vision inference path |

**Default weights:** `train/export/goods-and-gaps-chinese-2-yolo11n.onnx`

### Hard rules for agents

1. **All vision inference uses local weight files via `model-local/`.**  
   Do not load Ultralytics inside `agent/`. Do not reintroduce cloud/runtime Roboflow inference into the app path.
2. **Roboflow is for dataset download only** (`dataset/`), not live detection.
3. **Python deps: uv only.** Never add `requirements.txt` or document `pip install` for packages in this repo.
4. **Frontend deps: npm.** Do not mix package managers inside a package.
5. **API JSON is camelCase** (Pydantic `CamelModel` ↔ TypeScript types). Keep both sides in sync.
6. **Graceful degradation is intentional:** missing LLM key or offline model-local must return useful offline/mock responses, not crash the stack.
7. **Do not commit secrets**, datasets, training runs, or large weight dumps beyond what is already tracked under `train/export/` when required for demos.
8. Prefer **small, focused changes**. Match existing style (types, modules, CSS modules on frontend).

---

## Package responsibilities

### `frontend/` — React workspace

- Pages: Camera Stream, Shelf Audit, Agent Chat, Database.
- API modules under `src/api/`; hooks under `src/hooks/`; types under `src/types/`.
- Env:
  - `VITE_API_BASE_URL` → agent (`http://localhost:8000`); empty ⇒ chat/DB stubs.
  - `VITE_STREAM_BASE_URL` → model-local (`http://localhost:8001`).
- Shelf audit flow: **detect via model-local**, then send JSON to agent
  `POST /api/v1/audit/analyze-detections`. Planogram lookup is still a stub (`null`).
- Commands: `npm install` / `npm run dev` / `npm run build` / `npm run lint`.

### `agent/` — FastAPI backend

```text
agent/app/
  main.py          # app, CORS, /health
  config.py        # env settings (LOCAL_VISION_*, OPENAI_*)
  routers/         # audit, chat, database
  schemas/         # camelCase Pydantic models
  services/
    detector.py    # HTTP client → model-local (no YOLO load)
    agent.py       # LLM + offline narratives
    store.py       # in-memory records
```

Important endpoints:

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/v1/audit/analyze` | multipart image → model-local → narrative |
| POST | `/api/v1/audit/analyze-detections` | vision JSON → narrative |
| POST | `/api/v1/agent/chat` | JSON or multipart |
| GET | `/api/v1/database/records` | in-memory store |
| GET | `/health` | reports `visionBackend: model-local` |

Commands:

```bash
cd agent
uv sync
uv run uvicorn app.main:app --reload --port 8000
uv run pytest
```

### `model-local/` — local vision service

- `stream_server.py` — HTTP API (stream + detect).
- `detection.py` — camera backends (macOS AVFoundation / Linux V4L2 / CAP_ANY), drawing helpers.
- `main-on-screen.py` — OpenCV window for manual tests.
- Must remain the **single runtime detector** for the app.

Commands:

```bash
cd model-local
uv sync
uv run stream_server.py
uv run pytest
```

### `train/` — offline ML tooling

- `train.py` / `validate.py` / `predict.py` / `export.py` / `common.py`.
- Prepares polygon→box detection datasets when needed.
- Export ONNX into `train/export/` for app use.

```bash
cd train && uv sync
uv run python train.py --dataset-dir ../dataset/<name> --model yolo11n.pt
uv run python export.py --weights artifacts/<name>/train/weights/best.pt --format onnx
```

### `dataset/` — download only

```bash
cd dataset && uv sync
uv run python sku-gap-700img-yolov8.py
```

---

## Local stack (happy path)

Three processes, three terminals:

```bash
# 1 vision
cd model-local && uv sync && uv run stream_server.py

# 2 agent
cd agent && uv sync && cp -n .env.example .env && uv run uvicorn app.main:app --reload --port 8000

# 3 UI
cd frontend && cp -n .env.example .env && npm install && npm run dev
```

Open `http://localhost:5173`.

---

## Testing

| Area | Command |
| --- | --- |
| Agent | `cd agent && uv run pytest` |
| Model-local | `cd model-local && uv run pytest` |
| Frontend | `cd frontend && npm run build` (typecheck + build); `npm run lint` |

When changing agent offline paths, detector client, or camera helpers, **run the matching pytest suite** before finishing.

Agent includes `httpx` (runtime) and `httpx2` (silences Starlette TestClient deprecation). Keep both unless FastAPI/Starlette no longer requires it.

---

## Conventions

### Commits / PRs

Follow Conventional Commits (see human rules doc). Examples relevant here:

- `feat: match gaps to planogram slots`
- `fix: fall back to CAP_ANY on camera probe failure`
- `docs: document uv-only python workflow`
- `test: cover offline audit action paths`

### Code style

- **Python:** 3.11+, type hints, small modules, dataclasses/Pydantic where existing.
- **TS/React:** functional components, CSS modules, shared types in `src/types`.
- Prefer extending existing services over parallel “v2” stacks.
- Keep offline/mock paths working when LLM or vision is unavailable.

### Config / secrets

- Copy from `.env.example` only; never commit real keys.
- Agent: `OPENAI_*`, `LOCAL_VISION_*`, `APP_CORS_ORIGINS`.
- Frontend: `VITE_API_BASE_URL`, `VITE_STREAM_BASE_URL`.

### What not to do

- Do not put YOLO inference back into `agent/services/detector.py`.
- Do not revive `model-roboflow` (or similar) as a runtime dependency of UI/agent.
- Do not treat `model/` as the active training/runtime path (use `train/` + `model-local/`).
- Do not commit `dataset/*` downloads, `train/artifacts/`, or `.venv/`.
- Do not ignore `uv.lock` in git (locks are tracked per package).

---

## Known product gaps (intentional / incomplete)

These are real; fix only when the task asks for them:

- **Planogram matching** is not implemented (`queryPlanogramForDetections` → `null`).
- **Record store** is in-memory only (resets on process restart).
- **Chat attachments** currently pass filenames to the LLM path more than true multimodal image content.
- Multi-process local stack (no docker-compose yet).

---

## Where to read more

| Need | Doc |
| --- | --- |
| Product goals / gap strategy | `doc/instruction.md` |
| Human git/PR rules | `doc/developing_rules.md` |
| Agent API details | `agent/README.md` |
| Vision service | `model-local/README.md` |
| Training | `train/README.md` |
| UI | `frontend/README.md` |

When docs and code disagree, **prefer the code and this AGENTS.md**, then update the stale doc in the same change.
