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
AUTH_ADMIN_USERNAME=admin
AUTH_ADMIN_PASSWORD=change-me
```

When `AUTH_ENABLED=true`, all API routes except `/`, `/health`, and
`/api/v1/auth/*` require `Authorization: Bearer <token>`. The frontend shows a
login screen and attaches the token automatically.

Local demos keep `AUTH_ENABLED=false` (default) so the UI works without login.

## Graceful degradation

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
VITE_API_BASE_URL=http://localhost:8000
VITE_STREAM_BASE_URL=http://localhost:8001
```

## Tests

```bash
cd backend
uv sync
uv run pytest
```
