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
2. **Agent** reasons over detections + the active planogram to flag phantom inventory / restock actions.
3. **UI** lets staff stream cameras, build planograms, run audits, chat, and browse records.

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
├── backend/                  # FastAPI application API (:8000)
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
  └─ Chat / database / audit narrative ──► backend (:8000)
                                              │
                                              └─ image audits ──► model-local (:8001)
```

| Port | Process | Role |
| --- | --- | --- |
| 5173 | `frontend` (Vite) | Workspace UI (JWT login when auth enabled) |
| 8000 | `backend` (FastAPI) | App API: auth, SQL, planograms, media, LLM retail agent |
| 8001 | `model-local` (`stream_server.py`) | **Only** vision inference path |

**Default weights:** `train/export/gap-product-chinese-yolo11n.onnx`

### Hard rules for agents

1. **All vision inference uses local weight files via `model-local/`.**  
   Do not load Ultralytics inside `backend/`. Do not reintroduce cloud/runtime Roboflow inference into the app path.
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

- Pages: Shelf Audit, Planogram, Ticket Board, Agent Chat, Database.
  (Live camera streaming is integrated into Shelf Audit — there is no separate
  Camera Stream page.)
- API modules under `src/api/`; hooks under `src/hooks/`; types under `src/types/`.
- Env:
  - `VITE_API_BASE_URL` → backend (`http://localhost:8000`); empty ⇒ chat/DB/planogram local stubs.
  - `VITE_STREAM_BASE_URL` → model-local (`http://localhost:8001`).
- Planogram flow: upload a shelf photo, **draw facing rectangles by hand** on
  the image, fill item name / price / stock / SKU per region, then mark one
  planogram active.
- Shelf audit flow: each available camera renders as a **block** (cover = its
  latest capture, status label = auditing / not auditing) with quick
  start/stop, assigned planogram, and interval controls. **Refresh cameras**
  re-probes devices. Click a block to open its **live MJPEG stream** (only the
  opened camera streams) with full controls, upload, and analysis. Auditing is
  per-camera **background monitoring** (`useAuditAnalysis`): each camera keeps
  its own timer/config and keeps running when you open another camera or leave
  the page. Each camera can target its own planogram (threaded as an override
  through `analyze-detections`; falls back to the global active planogram).
  Detection is **via model-local**; matches go to the chosen planogram
  (`POST /api/v1/planograms/{id}/match`), then both JSON blobs to backend
  `POST /api/v1/audit/analyze-detections` (which also runs the closed-loop
  ticket pipeline). The `LocalDetectionResult` type carries the `occlusion`
  block + per-detection `obscured` flags; `PlanogramMatchResult` carries
  `obscuredMatches`. The offline planogram stub mirrors the same
  occlusion-skipping logic as the backend.
- Ticket board: kanban of action tickets, status transitions, verify re-scan,
  and admin webhook settings (Slack / WeCom / generic).
- Commands: `npm install` / `npm run dev` / `npm run build` / `npm run lint`.

### `backend/` — FastAPI application API

```text
backend/app/
  main.py          # app, CORS, lifespan init_db, /health
  config.py        # env settings (LOCAL_VISION_*, OPENAI_*, DATABASE_*, AUTH_*, DEBOUNCE_*)
  db/              # SQLAlchemy models + session (SQLite default / Postgres via URL)
  routers/         # auth, audit, chat, database, planogram, media, tickets
  schemas/         # camelCase Pydantic models
  services/
    detector.py         # HTTP client → model-local (no YOLO load)
    agent.py            # LLM retail agent + offline narratives
    closed_loop.py      # Detect → Decide → Dispatch → Verify ticket graph (+ temporal debounce)
    ticket_store.py     # SQL action tickets + status transitions
    observation_store.py # SQL finding observations for temporal debounce (Plan C)
    webhooks.py         # multi-endpoint Slack/WeCom/generic webhook dispatch
    store.py            # SQL record store (audits + image refs + detection JSON)
    planogram_store.py  # SQL planograms + active selection
    planogram_match.py  # map detection centers → slots (occlusion-aware: obscured facings skipped); also emits outOfStockSlots (stock<=0) independent of detections
    backup.py           # system backup zip export / validated restore
    auth.py             # JWT + bcrypt staff auth
    media.py            # on-disk image refs under backend/data/media
```

Important endpoints:

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/v1/auth/login` | username/password → JWT |
| GET | `/api/v1/auth/status` | `{ authEnabled, authenticated, ... }` |
| GET | `/api/v1/auth/me` | current user (auth when enabled) |
| POST | `/api/v1/audit/analyze` | multipart image → model-local → narrative + persisted audit + tickets |
| POST | `/api/v1/audit/analyze-detections` | vision JSON + optional imageBase64 → narrative + tickets |
| GET/POST | `/api/v1/tickets` | list / manually create action tickets |
| PATCH | `/api/v1/tickets/{id}` | update ticket status (open → done → …) |
| POST | `/api/v1/tickets/{id}/dispatch` | re-send webhook notification |
| POST | `/api/v1/agent/closed-loop/run` | Detect → Decide → Dispatch over a shelf snapshot (findings held by temporal debounce until confirmed) |
| POST | `/api/v1/agent/closed-loop/verify/{id}` | after done: re-scan, verify or escalate |
| GET/PUT | `/api/v1/admin/webhooks` | admin Slack/WeCom/generic webhook settings |
| POST | `/api/v1/admin/webhooks/test` | send a test webhook message |
| GET/POST | `/api/v1/planograms` | list / create planograms (SQL) |
| PUT | `/api/v1/planograms/active` | choose planogram used by audits |
| POST | `/api/v1/planograms/{id}/match` | match vision detections to freehand slots (obscured facings excluded from missingItems); also returns `outOfStockSlots` (every slot with stock ≤ 0), so the decision layer can open a backroom `out_of_stock` ticket even when no gap was detected |
| DELETE | `/api/v1/planograms/{id}` | delete planogram + its media image |
| DELETE | `/api/v1/database/records` | clear DB-page records + `media/audits` |
| GET | `/api/v1/database/backup` | download full system backup zip |
| POST | `/api/v1/database/backup/restore` | validate + restore backup zip |
| POST | `/api/v1/agent/chat` | JSON or multipart |
| GET | `/api/v1/database/records` | SQL store (optional keyword/type) |
| GET | `/api/v1/database/records/{id}` | single record with detection JSON / image refs |
| GET | `/api/v1/media/{path}` | serve stored audit/planogram images |
| GET | `/health` | reports `visionBackend: model-local`, `authEnabled`, DB scheme |

Commands:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
uv run pytest
```

### `model-local/` — local vision service

- `stream_server.py` — HTTP API (stream + detect). Live streams keep a small
  **ring buffer** of recent raw frames; `/detect/capture` medians a short
  **burst** (from the ring buffer when streaming, else a self-contained
  multi-frame grab) into an occlusion-free clean plate before detection. For
  non-streaming cameras the burst is **adaptive**: it escalates over a longer
  window (up to `burstMaxSeconds`, default 8s) while the view stays busy and
  stops early once it reads clean, so a customer *lingering* to choose/pick
  items is medianed out without slowing empty-shelf audits. A per-camera
  **long-baseline** of one downscaled frame per recent audit (spanning ~3 min,
  `useAuditHistory`) is folded into the median only — never the motion mask —
  so slow/lingering shoppers are out-voted over minutes at trivial memory cost.
- `detection.py` — camera backends (macOS AVFoundation / Linux V4L2 / CAP_ANY),
  drawing helpers, and temporal anti-occlusion helpers (`median_clean_plate`,
  `motion_occlusion_mask`, `occlusion_regions`, `detection_obscured`,
  `downscale_frame` / `unify_frames` for the long-baseline clean plate).
- `main-on-screen.py` — OpenCV window for manual tests.
- Must remain the **single runtime detector** for the app.
- **No person/COCO detector here.** Occlusion is derived from frame-difference
  motion on a fixed camera, not a second model (keeps the single-detector rule).
- Detect responses carry per-detection `obscured` flags, `summary.obscuredCount`,
  and an `occlusion` block (`coverage`, `viewObstructed`, normalized `regions`,
  `burstFrames`, `baselineFrames`, `escalated`). Optional burst tuning in the
  request body: `burstFrames` (default 7, set 1 to disable), `burstInterval`
  (default 0.12s), `burstMaxSeconds` (adaptive escalation budget, default 8s,
  set 0 to disable escalation), and `useAuditHistory` (long-baseline clean
  plate, default true).

Commands:

```bash
cd model-local
uv sync
uv run stream_server.py
uv run pytest
```

### `train/` — offline ML tooling

- `train.py` / `validate.py` / `predict.py` / `export.py` / `common.py`.
- `imbalance.py` — gap-vs-product class-imbalance policy (oversample gap images).
- `eval_report.py` — mAP + gap recall sweep + recommended conf thresholds.
- `merge_datasets.py` — pseudo-label products on gap-only sets, then merge.
- Prepares polygon→box detection datasets when needed.
- Export ONNX into `train/export/` for app use.

```bash
cd train && uv sync
# default --model is yolo11m.pt (recommended for merged-gap-product)
uv run python train.py --dataset-dir ../dataset/merged-gap-product --balance-gaps --device 0
uv run python eval_report.py --dataset-dir ../dataset/merged-gap-product --weights artifacts/merged-gap-product/train/weights/best.pt
uv run python merge_datasets.py build --teacher-weights artifacts/gap-product-chinese-2/train/weights/best.pt
uv run python export.py --weights artifacts/<name>/train/weights/best.pt --format onnx
```

### `dataset/` — download only

```bash
cd dataset && uv sync
uv run python sku-gap-700img-yolov8.py
```

Generated merge roots (`sku-gap-700img-1-with-products`, `merged-gap-product`)
are local only — build them via `train/merge_datasets.py` (see `train/README.md`).

---

## Local stack (happy path)

Three processes, three terminals:

```bash
# 1 vision
cd model-local && uv sync && uv run stream_server.py

# 2 backend
cd backend && uv sync && cp -n .env.example .env && uv run uvicorn app.main:app --reload --port 8000

# 3 UI
cd frontend && cp -n .env.example .env && npm install && npm run dev
```

Open `http://localhost:5173`.

---

## Testing

| Area | Command |
| --- | --- |
| Backend | `cd backend && uv run pytest` |
| Model-local | `cd model-local && uv run pytest` |
| Frontend | `cd frontend && npm run build` (typecheck + build); `npm run lint` |

When changing retail-agent offline paths, detector client, or camera helpers, **run the matching pytest suite** before finishing.

Backend includes `httpx` (runtime) and `httpx2` (silences Starlette TestClient deprecation). Keep both unless FastAPI/Starlette no longer requires it.

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
- Backend: `OPENAI_*`, `LOCAL_VISION_*`, `APP_CORS_ORIGINS`, `DATABASE_URL`, `AUTH_*`, `DEBOUNCE_*`.
- `DEBOUNCE_MIN_OBSERVATIONS` / `DEBOUNCE_WINDOW_SECONDS` / `DEBOUNCE_MIN_SPAN_SECONDS` / `DEBOUNCE_RETENTION_SECONDS` tune temporal false-positive suppression; set min observations to `1` and min span to `0` to disable. `DEBOUNCE_MIN_SPAN_SECONDS` is the busy-store persistence gate: a confirmed finding must also span that much wall-clock time (not just appear in N rapid-fire audits), so a customer choosing/picking items can't trip a false alarm.
- Frontend: `VITE_API_BASE_URL`, `VITE_STREAM_BASE_URL`.
- Default DB is SQLite at `backend/data/retail.db`; set `DATABASE_URL=postgresql://...` for Postgres.
- Set `AUTH_ENABLED=true` + a strong `AUTH_SECRET` for store deployment; the bootstrap account (`AUTH_ADMIN_USERNAME` / `AUTH_ADMIN_PASSWORD`) is seeded as the top-tier **owner** role (full control incl. account management) when the users table is empty. Three tiers: owner / admin / staff (owner manages accounts, admin writes everything except accounts, staff is read-only + chat); see `backend/README.md` → "Account tiers (RBAC)".

### What not to do

- Do not put YOLO inference back into `backend/app/services/detector.py`.
- Do not revive `model-roboflow` (or similar) as a runtime dependency of UI/backend.
- Do not treat `model/` as the active training/runtime path (use `train/` + `model-local/`).
- Do not commit `dataset/*` downloads, `train/artifacts/`, `backend/data/`, or `.venv/`.
- Do not ignore `uv.lock` in git (locks are tracked per package).

---

## Known product gaps (intentional / incomplete)

These are real; fix only when the task asks for them:

- **Planogram↔detection matching** maps each detection center into the smallest
  user-drawn planogram rectangle that contains it (not auto rows×cols grids).
- Multi-process local stack (no docker-compose yet).
- Auth has three account tiers (owner / admin / staff) with an in-app Accounts panel (owner-managed). The bootstrap account seeds as owner; older admin-only deploys are auto-promoted to owner on startup.
- `model-local/stream_server.py` is a raw `ThreadingHTTPServer` (fine for demos;
  FastAPI would share auth/CORS/OpenAPI with the backend but is not required yet).
- Frontend API types are hand-mirrored from Pydantic schemas (no OpenAPI → TS
  codegen). Keep both sides in sync when changing request/response shapes.
- **Occlusion/debounce are heuristics, not guarantees.** The motion mask assumes
  a fixed camera; a person standing perfectly still for a whole burst can still
  end up in the short-burst clean plate. That case is now mitigated three ways:
  the **adaptive burst** extends the capture window while the view stays busy;
  the **long-baseline** median folds in one downscaled frame per recent audit
  (spanning ~3 min) so a lingerer is out-voted over minutes; and the **wall-clock
  persistence gate** (`DEBOUNCE_MIN_SPAN_SECONDS`) refuses to confirm a gap that
  hasn't persisted across real time. None is a guarantee — a *perpetually* busy
  aisle confirms a real gap slowly (only during lulls), which is the intended
  trade (a ~2-min alarm is acceptable, a false alarm is not). Thresholds
  (`MOTION_DIFF_THRESHOLD`, `OBSCURED_OVERLAP_THRESHOLD`, `VIEW_OBSTRUCTED_COVERAGE`,
  `BURST_ESCALATE_COVERAGE`, `BURST_MAX_SECONDS`, `AUDIT_HISTORY_*` in
  `model-local/stream_server.py` / `detection.py`; `DEBOUNCE_*` env) are demo
  defaults and may need per-store tuning. The long-baseline window is
  intentionally bounded to ~the debounce window so a genuine sold-out gap still
  becomes the median majority within ~90s rather than being masked by stale
  product frames.
- **Long-baseline audit history is transient in-memory state.** It lives on the
  `DetectionStream` (streaming cameras) or the process-wide `AuditHistoryStore`
  (non-streaming), resets on stream stop / server restart, and is never
  persisted or backed up.
- `finding_observations` is transient debounce state — intentionally **not**
  included in the backup zip; it resets on a ticket-board wipe.

---

## Where to read more

| Need | Doc |
| --- | --- |
| Product goals / gap strategy | `doc/instruction.md` |
| Human git/PR rules | `doc/developing_rules.md` |
| Backend API details | `backend/README.md` |
| Vision service | `model-local/README.md` |
| Training | `train/README.md` |
| UI | `frontend/README.md` |

When docs and code disagree, **prefer the code and this AGENTS.md**, then update the stale doc in the same change.
