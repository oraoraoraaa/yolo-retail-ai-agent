# Frontend — YOLO Retail Agent

React + TypeScript + Vite workspace UI for live shelf streaming, shelf image audit, agent chat, and database browsing.

## Features

- **Camera Stream:** select a local camera from `model-local/stream_server.py` and view live YOLO bounding boxes.
- **Shelf Audit:** upload a local shelf image; display backend `suggestedAction` (small) and `explanation` (large).
- **Agent Chat:** chat with the retail agent; assistant replies render as Markdown (bold, lists, headings, code, tables via GFM).
- **API stubs:** when `VITE_API_BASE_URL` is empty, chat returns a sample Markdown reply so formatting can be verified offline.

## Project layout

```text
src/
  api/           HTTP client + endpoint modules (stubs when offline)
  components/    layout, audit panel, chat panel
  hooks/         audit + chat state orchestration
  lib/           small utilities
  styles/        design tokens + global styles
  types/         shared TypeScript contracts
```

## Environment

Copy the example env file (already present as `.env` for local use):

```bash
cp .env.example .env
```

| Variable | Description |
| --- | --- |
| `VITE_API_BASE_URL` | Backend origin. Leave empty to use stubs. Example: `http://localhost:8000` |
| `VITE_STREAM_BASE_URL` | Local model stream service origin. Defaults to `http://localhost:8001` |

Planned backend routes:

- `POST /api/v1/audit/analyze` — multipart field `image` → `{ suggestedAction, explanation }`
- `POST /api/v1/agent/chat` — JSON `{ message, history }` → `{ reply }`

Local model stream routes, served by `../model-local/stream_server.py`:

- `GET /api/v1/stream/cameras` — probe OpenCV camera indices.
- `POST /api/v1/stream/start` — JSON `{ camera }` starts annotated streaming.
- `GET /api/v1/stream/video` — MJPEG stream for the browser viewer.
- `POST /api/v1/stream/stop` — stop the active camera stream.

Vite also proxies `/api` → `http://localhost:8000` during local development when you switch the client to relative paths later.

## Setup

Requires Node.js 20+. Markdown chat rendering uses `react-markdown` + `remark-gfm` (installed into this frontend Node environment only).

```bash
cd frontend
npm ci   # or: npm install
npm run dev
```

For the live camera page, run the model stream service in another terminal:

```bash
cd ../model-local
uv sync
uv run stream_server.py
```

Other scripts:

```bash
npm run build    # typecheck + production build
npm run preview  # preview production build
npm run lint     # oxlint
```

Open `http://localhost:5173`.
