# yolo-retail-ai-agent

An AI Agent-driven inventory audit system combining YOLO object detection with LLM reasoning to detect phantom inventory, misplaced items, and automate stock replenishment.

## Instruction and Goal

See [instruction](doc/instruction.md).

## Quick start

### 1. Local vision service

Download the weight files using this [google drive link](https://drive.google.com/drive/folders/19nNcMQ2F7o4-Pcep1BDyll8wA9iFADFc?usp=sharing), and place them as:

```text
train/
└── export/
    ├── gap-product-chinese-yolo11n.onnx (default model, already present within repository)
    └── merged-gap-product.onnx
```

after the weight files are in place, run the following command:

```bash
cd model-local
uv sync
uv run stream_server.py
```

### 2. Application backend

```bash
cd backend
uv sync
cp .env.example .env
# Optional store deploy:
#   DATABASE_URL=postgresql://user:pass@localhost:5432/yolo_retail
#   AUTH_ENABLED=true
#   AUTH_SECRET=<long-random>
uv run uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
cp .env.example .env
# Recommended for local / LAN testing: leave VITE_API_BASE_URL empty so Vite
# proxies /api → backend (same-origin, no CORS). Set an absolute origin only
# when you intentionally call the backend directly.
#   VITE_API_BASE_URL=http://localhost:8000
# set VITE_STREAM_BASE_URL=http://localhost:8001
npm install
npm run dev
# LAN / phone: npm run dev -- --host
```

Open `http://localhost:5173`. When `AUTH_ENABLED=true` on the backend, the UI
shows a login screen. The bootstrap account (default `owner` / `owner`) is
seeded as the top-tier **owner** role — full control including account
management. Create `admin` and `staff` users from the in-app Accounts panel.

If login fails with `OPTIONS /api/v1/auth/login 400` / "Disallowed CORS origin",
either leave `VITE_API_BASE_URL` empty (proxy path) or ensure the UI origin is
allowed by `APP_CORS_ORIGINS` / the default private-LAN CORS regex.

## Develop

> Contents below are for developers only. Read them carefully before you do the actual work and make a git push.
>
> ![miku_for_developers](./doc/images/banner/miku_for_developers.png)

- [DEVELOPING RULES](./doc/developing_rules.md)

## Frontend Architecture

All vision inference uses **local weight files** via `model-local/`:

```text
frontend (:5173)
  ├─ stream / detect ──► model-local (:8001) ──► train/export/*.onnx
  └─ chat / DB / auth ──► backend (:8000)
                              ├─ SQLite (default) or Postgres
                              ├─ audit media under backend/data/media/
                              ├─ JWT auth when AUTH_ENABLED=true
                              └─ LLM retail agent (services/agent.py)
```

Default weights: `train/export/gap-product-chinese-yolo11n.onnx`

### Busy-store robustness

Because the model needs the whole shelf in frame, customers walking past would
otherwise read as gaps (or trip a false `camera_issue`). Layered suppression
handles this, including slow/lingering shoppers who choose and pick items:

- **Median clean plate** over a frame burst — moving shoppers vanish. The burst
  is **adaptive** (extends its window while the view stays busy, stays fast when
  the shelf is clear) and backed by a **long baseline** of recent audit frames,
  so a shopper lingering at a facing is out-voted over minutes.
- **Occlusion gating** — obscured facings are skipped, not ticketed; a blocked
  lens is not reported as a broken camera.
- **Temporal debounce** — a finding must be seen in several audits **and persist
  across real wall-clock time** (`DEBOUNCE_MIN_SPAN_SECONDS`) before a ticket
  opens, so a brief obstruction can't confirm a gap.

Latency is intentionally not prioritized (a ~2-minute alarm is fine); a false
alarm is not. Tunable via `DEBOUNCE_*` env vars and the burst constants — see
[backend/README.md](backend/README.md) and [model-local/README.md](model-local/README.md).

## Dependency management

All **Python** packages in this repo are managed with **[uv](https://docs.astral.sh/uv/)**:

| Package | Path | Command |
| --- | --- | --- |
| Backend API | `backend/` | `uv sync && uv run …` |
| Local vision | `model-local/` | `uv sync && uv run …` |
| Training | `train/` | `uv sync && uv run …` |
| Dataset download | `dataset/` | `uv sync && uv run …` |

Frontend remains **npm** (`frontend/`).

## Training & datasets

- Training: [train/README.md](train/README.md) — `cd train && uv sync && uv run python train.py …`
- Dataset download (Roboflow API key for **download only**):
  - [sku-gap-700img-yolov8.py](dataset/sku-gap-700img-yolov8.py)
  - [gap-product-chinese-yolov8.py](dataset/gap-product-chinese-yolov8.py)
  - [gap-product-yolov8.py](dataset/gap-product-yolov8.py)

  ```bash
  cd dataset && uv sync && uv run python sku-gap-700img-yolov8.py
  ```

## Tests

Each package is tested independently. Run the suite for whatever you touched
(and the frontend build, which doubles as the type check):

| Area | What it covers | Command |
| --- | --- | --- |
| Backend | Closed-loop tickets, temporal debounce + wall-clock persistence gate, webhooks, planogram match, backup/restore, RBAC, offline agent paths | `cd backend && uv run pytest` |
| Model-local | Median clean plate, motion-occlusion mask, adaptive burst + long-baseline helpers (pure numpy/cv2 — no camera or weights needed) | `cd model-local && uv run pytest` |
| Frontend | Typecheck + production build (no unit suite yet) | `cd frontend && npm run build` |
| Training | Train/validate/eval CLIs, dataset merge, class-imbalance policy | `cd train && uv run pytest` |

Run a single file or test while iterating, e.g.:

```bash
cd backend && uv run pytest tests/test_closed_loop.py -q
cd model-local && uv run pytest tests/test_occlusion.py -q
```

When you change retail-agent offline paths, the detector client, camera helpers,
or the occlusion/debounce logic, run the matching suite before pushing.
