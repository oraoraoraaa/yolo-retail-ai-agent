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

Interactive docs: `http://localhost:8000/docs`.

## Graceful degradation

- **Local vision service offline** → informative placeholder (no hard crash).
- **No `OPENAI_API_KEY`** → deterministic offline chat/audit narratives.

## Setup (uv)

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
cd agent
uv sync
cp .env.example .env   # optional

# In another terminal, start local vision first:
cd ../model-local && uv sync && uv run stream_server.py

# Start the agent:
cd ../agent
uv run uvicorn app.main:app --reload --port 8000
# or: uv run python main.py
```

### Local weights

Default: `train/export/goods-and-gaps-chinese-2-yolo11n.onnx`  
Override with `LOCAL_VISION_MODEL` / `LOCAL_VISION_BASE_URL` in `.env`.

## Connect the frontend

```bash
# frontend/.env
VITE_API_BASE_URL=http://localhost:8000
VITE_STREAM_BASE_URL=http://localhost:8001
```

## Tests

```bash
cd agent
uv sync
uv run pytest
```
