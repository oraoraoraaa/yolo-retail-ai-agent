# Frontend — YOLO Retail Agent

React + TypeScript + Vite workspace UI for live shelf streaming, shelf image audit, agent chat, and database browsing.

## Features

- **Camera Stream:** select a local camera from `model-local/stream_server.py` and view live YOLO bounding boxes (local weight files).
- **Shelf Audit:** upload a local shelf image or run low-frequency camera monitoring; send detector JSON to the agent and display the suggested action and explanation. Audits are persisted with image refs + detection JSON.
- **Planogram:** draw freehand facing regions and mark one planogram active for audits.
- **Agent Chat:** chat with the retail agent; assistant replies render as Markdown (bold, lists, headings, code, tables via GFM).
- **Database:** browse durable SQL records; open an audit to view image + detection JSON.
- **Auth:** when the backend has `AUTH_ENABLED=true`, the UI shows a login gate and attaches JWT Bearer tokens to API calls.
- **API stubs:** when `VITE_API_BASE_URL` is empty, chat/database use offline stubs.

## Project layout

```text
src/
  api/           HTTP client + endpoint modules (stubs when offline)
  components/    layout, auth login, audit, chat, database, planogram, stream
  hooks/         auth + audit + chat state orchestration
  lib/           i18n + small utilities
  styles/        design tokens + global styles
  types/         shared TypeScript contracts
```

## Environment

```bash
cp .env.example .env
```

| Variable | Description |
| --- | --- |
| `VITE_API_BASE_URL` | Backend API origin. Leave empty to use chat/database stubs. Example: `http://localhost:8000` |
| `VITE_STREAM_BASE_URL` | Local model stream service origin. Defaults to `http://localhost:8001` |

### Vision path (local weights only)

All vision requests go to `model-local` (local ONNX/YOLO weights under `train/export/`):

- `GET /api/v1/stream/cameras` — probe OpenCV camera indices.
- `GET /api/v1/stream/models` — list selectable local model weights.
- `POST /api/v1/stream/start` — JSON `{ camera }` starts annotated streaming.
- `GET /api/v1/stream/video` — MJPEG stream for the browser viewer.
- `POST /api/v1/stream/stop` — stop the active camera stream.
- `POST /api/v1/detect/image` — JSON image payload → annotated image + detection JSON.
- `POST /api/v1/detect/capture` — JSON `{ camera, model }` → one camera capture detection.

The Shelf Audit agent step sends local detector JSON (and optional image base64)
to the backend `POST /api/v1/audit/analyze-detections`, which persists the
audit and returns `{ suggestedAction, explanation, recordId }`.

Vite also proxies `/api` → `http://localhost:8000` during local development when you switch the client to relative paths later.

## Setup

Requires Node.js 20+. Markdown chat rendering uses `react-markdown` + `remark-gfm`.

```bash
cd frontend
npm ci   # or: npm install
npm run dev
```

For the live camera / audit detection path, run the model stream service:

```bash
cd ../model-local
uv sync
uv run stream_server.py
```

For backend chat / LLM narratives:

```bash
cd ../backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Other scripts:

```bash
npm run build    # typecheck + production build
npm run preview  # preview production build
npm run lint     # oxlint
```

Open `http://localhost:5173`.
