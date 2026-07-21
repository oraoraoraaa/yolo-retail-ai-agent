# Model Local Webcam Inference

Local ONNX/YOLO weight files only — the sole runtime vision backend for the app.

- `stream_server.py` — HTTP API on port `8001` (stream + detect)
- `main-on-screen.py` — OpenCV preview window
- `detection.py` — shared camera backends + drawing helpers

## Setup (uv)

```bash
uv sync
```

Default weights: `../train/export/gap-product-chinese-yolo11n.onnx`

## Run

```bash
uv run stream_server.py
# http://localhost:8001
```

On-screen test:

```bash
uv run main-on-screen.py --weights ../train/export/gap-product-chinese-yolo11n.onnx
# or defaults:
uv run main-on-screen.py --camera 0
```

### Endpoints

- `GET /health`
- `GET /api/v1/stream/cameras`
- `GET /api/v1/stream/models`
- `POST /api/v1/stream/start` — `{ "camera": "0" }`
- `GET /api/v1/stream/video` — MJPEG
- `POST /api/v1/stream/stop`
- `POST /api/v1/detect/image`
- `POST /api/v1/detect/capture`
- `POST /api/v1/detect/snapshot` — clean-plate still only (no detection), for planogram photos

## Temporal anti-occlusion (busy-store false positives)

A camera facing a shelf in a busy store constantly has customers walking
through frame. A single snapshot of a person in front of a facing reads as a
`gap`, and one covering the lens reads as zero detections (a false
`camera_issue`). To resolve the shelf *behind* transient occluders, `/detect/capture`
works on a short **burst** of frames rather than one snapshot:

- **Clean plate.** The per-pixel **median** of the burst removes anyone who
  moves at all — a shopper occupying a pixel only briefly is the minority
  across the window, so the median resolves to the shelf. Detection runs on
  this composite. (`detection.median_clean_plate`)
- **Occlusion mask.** Pixels that differ from the clean-plate luminance in any
  frame form a motion mask (no new model — the camera is fixed).
  (`detection.motion_occlusion_mask`, `occlusion_regions`, `detection_obscured`)

### Slow / lingering customers (not just walkers)

A sub-second burst clears someone walking *briskly* past, but a shopper who
*lingers* to choose and pick items occupies a facing for several seconds and
survives that short window. Two extra mechanisms handle them:

- **Adaptive burst.** When the initial burst is still busy (motion coverage
  ≥ `BURST_ESCALATE_COVERAGE`), the capture keeps extending its window — up to
  `BURST_MAX_SECONDS` / `BURST_MAX_FRAMES` — and stops early once the scene
  reads clean. Over ~5s a slow walker is a minority at any pixel, so the median
  still resolves to the shelf. Empty-shelf audits read clean immediately and
  never escalate, so they stay fast (latency is paid only when the view is
  actually busy). (`capture_burst_adaptive`, non-streaming cameras only.)
- **Long-baseline clean plate.** One **downscaled** frame per audit is retained
  per camera (spanning ~`AUDIT_HISTORY_MAX_AGE_SECONDS`, default 180s) and
  folded into the median so a lingerer is out-voted over minutes at trivial
  memory cost. Baseline frames feed the **median only, never the motion mask**
  (motion needs close-in-time frames). The window is bounded to ~the backend
  debounce window on purpose: long enough to out-vote a lingerer, short enough
  that a genuine sold-out gap becomes the median majority within ~90s instead
  of being masked by stale product frames. (`AuditHistoryStore` for
  non-streaming cameras; the `DetectionStream`'s own history when streaming.)

A false gap that slips through all of the above is still caught by the backend
**temporal debounce + wall-clock persistence gate** (`DEBOUNCE_MIN_SPAN_SECONDS`):
a finding must persist across real time before a ticket opens, so no customer
behaviour — walk, linger, or pick — can trip a false alarm.

### The three circumstances (how the frame source is chosen)

`/detect/capture` picks its frames from whether the camera is currently
streaming, **not** from how the request was triggered. The frontend "Analyze
now" button, background auto-audits, and the verify re-scan all hit this same
endpoint, so they behave identically for the same streaming state:

1. **Normal auditing (camera not streaming).** The common background-audit case:
   no live worker holds the device, so `/detect/capture` grabs a self-contained
   **adaptive burst** (opens the device, escalates while busy, releases) and
   folds in the camera's long-baseline history from the process-wide
   `AuditHistoryStore`. Full stack: adaptive burst + long baseline + occlusion
   mask, then this frame is appended to the baseline for next time.

2. **Streaming is opened (live view of this camera).** The streaming worker
   already holds the V4L2 device, so `/detect/capture` must **not** reopen it —
   it reuses the last `burstFrames` raw frames from the stream's **ring buffer**
   (continuously refreshed by the worker, so a moving shopper is still cleared)
   plus the stream's own retained audit-history baseline. No adaptive escalation
   here (the ring buffer is the frame source, not a capture loop we control),
   but the long baseline still out-votes a lingerer.

3. **Streaming open + "Analyze now" clicked.** Same as case 2 — "Analyze now"
   calls `submitCameraCapture` → `POST /api/v1/detect/capture`, which detects
   the live stream and reuses its ring buffer + baseline. The manual click is
   just an on-demand trigger of the same background pipeline; there is no
   separate code path and no device contention.

In every case the result carries the same `occlusion` block, so the backend
decision + debounce layers treat manual and automatic audits identically.

`/detect/capture` and `/detect/image` accept optional tuning in the JSON body:

| Field | Default | Meaning |
| --- | --- | --- |
| `burstFrames` | `7` | Frames to median into a clean plate (`1` = single-snapshot, disables it) |
| `burstInterval` | `0.12` | Seconds between burst frames (non-streaming capture only) |
| `burstMaxSeconds` | `8` | Adaptive-escalation time budget; `0` disables escalation (non-streaming only) |
| `useAuditHistory` | `true` | Fold the long-baseline recent-audit frames into the clean plate |

Added response fields (consumed by the backend decision layer):

- `summary.obscuredCount` — detections whose box overlaps the motion mask.
- each detection carries `obscured: bool`.
- `occlusion: { coverage, viewObstructed, regions[], burstFrames, baselineFrames, escalated }` —
  `viewObstructed` is true when motion covers most of the frame (a customer in
  front of the lens), which the backend uses to suppress a false `camera_issue`;
  `regions` are normalized `[0,1]` motion boxes projected onto planogram slots;
  `baselineFrames` is how many long-baseline frames were folded in; `escalated`
  is true when the adaptive burst extended its window.

## Camera backends

| OS | Preferred | Fallback |
| --- | --- | --- |
| Linux | `CAP_V4L2` | `CAP_ANY` |
| macOS | `CAP_AVFOUNDATION` | `CAP_ANY` |
| Windows | `CAP_DSHOW` / `CAP_MSMF` | `CAP_ANY` |

## Tests

```bash
uv run pytest
```
