# CanvasAI Backend

FastAPI backend service powering CanvasAI's single-mode generative conversation and adaptive UI streaming with **LangChain** and **Google Gemini**.

## Architecture & Endpoints

The backend is built with **FastAPI** (Python 3.12+) and integrates **Google Gemini** through LangChain (`langchain-google-genai`).

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check returning status and the active Gemini model name. |
| `POST` | `/api/chat/stream` | Server-Sent Events (SSE) streaming generative conversation with interleaved text and validated UI components. |
| `POST` | `/api/chat` | Non-streaming fallback endpoint for standard chat completions. |
| `POST` | `/api/ui-plan` | Developer endpoint proposing a structured `UIPlan` via LangChain's `with_structured_output`. |

---

## Wire Protocol (SSE Events)

The `/api/chat/stream` endpoint emits W3C-compliant Server-Sent Events:

- `event: start` — Emits `{"event": "start", "message_id": "<uuid>", "model": "<name>"}`
- `event: status` — Emits progress updates (e.g. `{"event": "status", "status": "Analyzing request & planning adaptive UI..."}`)
- `event: token` — Emits incremental prose text chunks `{"event": "token", "delta": "..."}`
- `event: ui_component` — Emits validated UI component specifications `{"event": "ui_component", "component": {...}, "block_id": "<uuid>"}`
- `event: done` — Emits stream completion `{"event": "done", "finish_reason": "stop"}`
- `event: error` — Emits sanitized error message on failure `{"event": "error", "message": "..."}`

---

## Setup & Running

### Requirements
- Python 3.12+
- `uv` package manager

### Installation

1. Navigate to the backend directory:
   ```bash
   cd CanvasAI/backend
   ```

2. Copy the example configuration:
   ```bash
   cp .env.example .env
   ```

3. Configure your API key in `.env`:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-3.5-flash-lite
   ```

4. Run the development server with live reload:
   ```bash
   uv run uvicorn app.main:app --reload --port 8000
   ```

---

## Testing

Run tests using pytest via `uv`:

```bash
uv run pytest -v
```

This executes:
- `tests/test_health.py`: Verifies `/health` endpoint status.
- `tests/test_planning.py`: Verifies all 19 Pydantic component schemas and URL validation.
- `tests/test_stream.py`: Verifies SSE chunking, event ordering, and cancellation.
