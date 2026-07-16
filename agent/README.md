# Backend — YOLO Retail Agent

FastAPI service powering the shelf-audit workspace UI in [`frontend/`](../frontend).
It provides an LLM-backed retail agent, a lightweight in-memory record store, and
**proxies all shelf vision inference to the local model service**
([`model-local/`](../model-local)) which loads local weight files.

## Architecture

```text
frontend ──► agent (:8000) ──► model-local (:8001) ──► local ONNX/YOLO weights
                │                    ▲
                └── chat / records   └── also used directly by frontend stream/audit
```

The agent **does not** load Ultralytics itself. Image detection always goes through
`model-local/stream_server.py` and the weights under `train/export/`.

## API

All responses use camelCase to match the frontend TypeScript contracts.

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| `POST` | `/api/v1/audit/analyze` | multipart `image` | `{ suggestedAction, explanation }` |
| `POST` | `/api/v1/audit/analyze-detections` | JSON `{ visionModelResponse, planogramResponse }` | `{ suggestedAction, explanation }` |
| `POST` | `/api/v1/agent/chat` | JSON `{ message, history }` or multipart (`message`, `history`, `images[]`) | `{ reply }` |
| `GET` | `/api/v1/database/records` | query `keyword?`, `type?` | `{ records: DatabaseRecord[] }` |
| `GET` | `/health` | — | service + feature availability |

Interactive docs are available at `http://localhost:8000/docs` once running.

## Graceful degradation

The service starts and answers requests even with nothing configured:

- **Local vision service offline** → the audit endpoint returns an informative
  placeholder instead of failing hard.
- **No `OPENAI_API_KEY`** → the chat + audit narratives use a deterministic
  offline reply.

Enable the real features by editing `.env` (see `.env.example`).

## Layout

```text
app/
  main.py        FastAPI app, CORS, router registration
  config.py      env-driven settings (+ simple .env loader)
  schemas/       Pydantic models (camelCase aliases)
  routers/       audit / chat / database endpoints
  services/      detector (HTTP → model-local) · agent (LLM) · in-memory store
```

## Setup

Requires Python 3.10+.

```bash
cd agent
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux:        source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional; adjust values

# In another terminal, start the local vision service first:
cd ../model-local
uv sync
uv run stream_server.py

# Then start the agent:
cd ../agent
uvicorn app.main:app --reload --port 8000
```

### Local weights

Default weights path (relative to repo root):

```text
train/export/goods-and-gaps-chinese-2-yolo11n.onnx
```

Override with `LOCAL_VISION_MODEL` / `LOCAL_VISION_BASE_URL` in `.env`.

## Connect the frontend

```bash
# frontend/.env
VITE_API_BASE_URL=http://localhost:8000
VITE_STREAM_BASE_URL=http://localhost:8001
```

The default CORS allow-list already includes `http://localhost:5173`.

## Tests

```bash
cd agent
pip install -r requirements.txt
pytest
```
