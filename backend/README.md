# Backend — YOLO Retail application API

FastAPI service powering the shelf-audit workspace UI in [`frontend/`](../frontend).
It owns **auth, SQL persistence, planograms, media, and the LLM retail agent**,
and **proxies all shelf vision inference to the local model service**
([`model-local/`](../model-local)) which loads local weight files.

## Naming

| Name | Meaning |
| --- | --- |
| **`backend/`** | This package — the application API process on `:8000` |
| **Retail agent** | LLM reasoning component inside `app/services/agent.py` |
| **`/api/v1/agent/chat`** | Stable HTTP route for chat (kept for API compatibility) |

## Architecture

```text
frontend ──► backend (:8000) ──► model-local (:8001) ──► local ONNX/YOLO weights
                │                    ▲
                ├── chat / records / planograms (SQLite or Postgres)
                ├── media files under backend/data/media/
                ├── JWT auth when AUTH_ENABLED=true
                └── LLM retail agent (services/agent.py)
```

The backend **does not** load Ultralytics itself. Image detection always goes through
`model-local/stream_server.py` and the weights under `train/export/`.

## API

All responses use camelCase to match the frontend TypeScript contracts.

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/login` | `{ username, password }` | `{ accessToken, username, role, ... }` |
| `GET` | `/api/v1/auth/status` | — | `{ authEnabled, authenticated, ... }` |
| `POST` | `/api/v1/audit/analyze` | multipart `image` | `{ suggestedAction, explanation, recordId? }` |
| `POST` | `/api/v1/audit/analyze-detections` | JSON vision + optional `imageBase64` | `{ suggestedAction, explanation, recordId? }` |
| `POST` | `/api/v1/agent/chat` | JSON `{ message, history }` or multipart | `{ reply }` |
| `GET` | `/api/v1/database/records` | query `keyword?`, `type?` | `{ records: DatabaseRecord[] }` |
| `GET` | `/api/v1/database/records/{id}` | — | full record incl. detection JSON / image refs |
| `GET` | `/api/v1/media/{path}` | — | stored audit/planogram image bytes |
| `GET` | `/health` | — | service + feature availability |

Interactive docs: `http://localhost:8000/docs`.

## Persistence

- **Default:** SQLite file at `backend/data/retail.db`.
- **Postgres:** set `DATABASE_URL=postgresql://user:pass@host:5432/dbname`.
- Audit rows store optional `imageRef` (file under `backend/data/media/audits/`) plus
  `detectionJson` / `planogramJson`.
- Planograms and the active planogram id are also SQL-backed.

## Auth (store deployment)

```bash
# backend/.env
AUTH_ENABLED=true
AUTH_SECRET=replace-with-a-long-random-string
AUTH_ADMIN_USERNAME=owner
AUTH_ADMIN_PASSWORD=change-me
```

When `AUTH_ENABLED=true`, all API routes except `/`, `/health`, and
`/api/v1/auth/*` require an `Authorization: Bearer` token header. The frontend
shows a login screen and attaches the token automatically.

Local demos keep `AUTH_ENABLED=false` (default) so the UI works without login.

### Account tiers (RBAC)

Three account roles, enforced by backend dependencies (frontend gating is UX
only):

| Role | Can do |
| --- | --- |
| `owner` | Everything, **including account management** (add/edit/delete users). |
| `admin` | Change everything **except** accounts (accounts are view-only). |
| `staff` | Chat with the agent + view cameras only — **no changes anywhere**. |

`AUTH_ADMIN_USERNAME` / `AUTH_ADMIN_PASSWORD` seed the bootstrap account when the
users table is empty; it is created as the top-tier **`owner`** so the Accounts
panel is reachable on first login. Create `admin` / `staff` users from that
panel afterwards. Older admin-only deployments are auto-upgraded: if no owner
exists, the bootstrap admin account is promoted to owner on startup. Mutating
endpoints carry the `require_write` dependency (rejects `staff`); account
management carries `require_account_admin` (owner only).

## Ticket rules (findings → assignee)

`extract_findings` (in `services/closed_loop.py`) turns a vision + planogram
match into action tickets. One SKU produces **at most one ticket per issue
type** (facings are aggregated first):

- **`out_of_stock` → backroom.** Planogram stock ≤ 0 is staff-entered **ground
  truth**, so this ticket opens **the moment stock is 0, whether or not the
  camera detected a gap** (the last unit may still be on the shelf, or the
  facing may be occluded this frame). `planogram_match` surfaces every stock-0
  slot as `outOfStockSlots`, independent of detections, and the finding fires
  even when vision saw nothing at all. Because it is ground truth (not a flaky
  vision reading), `out_of_stock` **bypasses the temporal debounce/span gate**
  and dispatches immediately.
- **`shelf_empty` → floor_staff.** A gap facing that matches a planogram item
  whose stock is **> 0 or unknown** — a floor restock/facing task.
- **Empty facing (gap matches a stock-0 item)** opens the `out_of_stock`
  backroom ticket **only** (no companion floor ticket), plus one store-wide
  announcement.
- **`low_stock` → backroom** on severity bands; **`camera_issue` →
  floor_staff + manager** (suppressed when the view is occlusion-obstructed).

**No re-issue for the same problem.** Every finding carries a fingerprint
`(issueType, planogramId, skuKey)`. The gap-matched and planogram-driven
out-of-stock paths share the **same** fingerprint, so whichever fires first
opens the ticket and the other dedupes against the open ticket
(`find_open_by_fingerprint` covers open/dispatched/in_progress/escalated/done).
An out-of-stock SKU therefore never opens two tickets, and re-audits do not
re-notify while the ticket stays open.

## False-positive suppression (busy-store occlusion)

In a busy store, customers constantly walk between the camera and the shelf. A
person standing in front of a facing reads as a `gap` (and, when they fill the
frame, as zero detections → a false `camera_issue`). Three layers cooperate to
stop a single occluded snapshot from firing a bogus ticket:

1. **Temporal clean plate + occlusion mask (model-local).** Audits capture a
   short burst of frames and detect on their per-pixel median, so anyone who
   moves is removed. A motion mask flags boxes/regions that stayed busy and is
   returned as an `occlusion` block plus per-detection `obscured` flags. See
   [`model-local/README.md`](../model-local/README.md).
2. **Occlusion-aware gating (backend).** `planogram_match` reports obscured gaps
   with `status="obscured"` and keeps them **out** of `missingItems`, so an
   occluded facing can never open a restock ticket. Slots whose center falls in
   a reported occlusion region are treated the same even with no detection of
   their own (a fully-covered facing). `extract_findings` suppresses
   `camera_issue` when the vision layer reports the view is obstructed by
   motion (a customer in front of the lens is not a broken camera).
3. **Temporal debounce (backend).** Before opening a **new** ticket, a finding
   must be observed in at least `DEBOUNCE_MIN_OBSERVATIONS` audits inside the
   trailing `DEBOUNCE_WINDOW_SECONDS` window (scoped per shelf/camera via the
   audit `sourceLabel`). A transient gap that vanishes on the next audit never
   reaches the threshold; a genuinely empty shelf persists and gets ticketed.
   Observations are stored in the `finding_observations` table and reset when
   the ticket board is wiped. Set `DEBOUNCE_MIN_OBSERVATIONS=1` to disable.
   Debounce gates **vision-derived** findings only (gaps, camera issues);
   planogram `out_of_stock` is ground truth and bypasses it.

Debounced (awaiting-confirmation) findings appear in the closed-loop result's
`debounced` list and are summarized in the narrative; they are not errors.

Relevant env (see `.env.example`): `DEBOUNCE_MIN_OBSERVATIONS`,
`DEBOUNCE_WINDOW_SECONDS`, `DEBOUNCE_RETENTION_SECONDS`.

## Degradation

- **Local vision service offline** → informative placeholder (no hard crash).
- **No `OPENAI_API_KEY`** → deterministic offline chat/audit narratives.

## Setup (uv)

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
cd backend
uv sync
cp .env.example .env   # optional

# In another terminal, start local vision first:
cd ../model-local && uv sync && uv run stream_server.py

# Start the backend API:
cd ../backend
uv run uvicorn app.main:app --reload --port 8000
# or: uv run python main.py
```

### Local weights

Default: `train/export/gap-product-chinese-yolo11n.onnx`  
Override with `LOCAL_VISION_MODEL` / `LOCAL_VISION_BASE_URL` in `.env`.

## Connect the frontend

```bash
# frontend/.env
# Prefer empty for local/LAN (Vite proxies /api → :8000, no CORS):
VITE_API_BASE_URL=
# Or call the backend directly (requires CORS allowlist / private-LAN regex):
# VITE_API_BASE_URL=http://localhost:8000
VITE_STREAM_BASE_URL=http://localhost:8001
```

`APP_CORS_ORIGINS` defaults to `http://localhost:5173,http://127.0.0.1:5173`.
A private-LAN origin regex is also enabled by default so phone testing via
`npm run dev -- --host` works without listing every DHCP IP. Override with
`APP_CORS_ORIGIN_REGEX` (empty disables the regex).

## Tests

```bash
cd backend
uv sync
uv run pytest
```
