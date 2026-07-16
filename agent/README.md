# Backend — YOLO Retail Agent

FastAPI service powering the shelf-audit workspace UI in [`frontend/`](../frontend).
It provides shelf-gap detection (YOLOv8), an LLM-backed retail agent, and a
lightweight in-memory record store.

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

- **No YOLO weights / no `ultralytics`** → the audit endpoint returns an
  informative placeholder instead of failing.
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
  services/      detector (YOLO) · agent (LLM) · in-memory store
```

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux:        source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional; adjust values

uvicorn app.main:app --reload --port 8000
```

### Enable real detection (optional)

```bash
pip install -r ../model/gap-detection/requirements.txt
# then point YOLO_WEIGHTS_PATH at your trained best.pt (see model/gap-detection)
```

## Connect the frontend

Set the frontend origin so it calls this server instead of using stubs:

```bash
# frontend/.env
VITE_API_BASE_URL=http://localhost:8000
```

The default CORS allow-list already includes `http://localhost:5173`.
