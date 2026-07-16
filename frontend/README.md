# Frontend — YOLO Retail Agent

React + TypeScript + Vite workspace UI for shelf image audit and agent chat.

## Features

- **Left panel:** upload a local shelf image; display backend `suggestedAction` (small) and `explanation` (large).
- **Right panel:** chat with the retail agent; assistant replies render as Markdown (bold, lists, headings, code, tables via GFM).
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

Planned backend routes:

- `POST /api/v1/audit/analyze` — multipart field `image` → `{ suggestedAction, explanation }`
- `POST /api/v1/agent/chat` — JSON `{ message, history }` → `{ reply }`

Vite also proxies `/api` → `http://localhost:8000` during local development when you switch the client to relative paths later.

## Setup

Requires Node.js 20+. Markdown chat rendering uses `react-markdown` + `remark-gfm` (installed into this frontend Node environment only).

```bash
cd frontend
npm ci   # or: npm install
npm run dev
```

Other scripts:

```bash
npm run build    # typecheck + production build
npm run preview  # preview production build
npm run lint     # oxlint
```

Open `http://localhost:5173`.
