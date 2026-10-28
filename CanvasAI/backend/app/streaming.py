from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncIterator, List, Optional
from fastapi import Request
from langchain_core.messages import BaseMessage

from app.llm import extract_text_delta
from app.planning import generate_generative_plan

logger = logging.getLogger(__name__)


def format_sse(event: str, data: dict[str, Any]) -> str:
    """Format an SSE message according to the W3C EventSource standard."""
    json_payload = json.dumps(data)
    return f"event: {event}\ndata: {json_payload}\n\n"


def sanitize_error_message(exc: Exception) -> str:
    """Produce a safe, user-facing error message without internal stack traces or secrets."""
    msg = str(exc)

    if "api_key" in msg.lower() or "unauthorized" in msg.lower() or "401" in msg or "403" in msg:
        return "Authentication failed with AI provider. Please verify your Gemini API key."
    if "quota" in msg.lower() or "rate limit" in msg.lower() or "429" in msg or "resourceexhausted" in msg.lower():
        return "Gemini API rate limit or quota exceeded. Please wait a moment and try again."
    if "timeout" in msg.lower() or "timed out" in msg.lower() or "connection" in msg.lower():
        return "Connection to Gemini timed out. Please try again."

    return "An error occurred while generating the response. Please try again."


async def stream_chat_response(
    messages: List[BaseMessage],
    model: Any,
    model_name: str,
    request: Optional[Request] = None,
) -> AsyncIterator[str]:
    """Stream chat response tokens using LangChain model.astream() (Phase 1 preserved)."""
    message_id = str(uuid.uuid4())
    error_occurred = False

    yield format_sse("start", {
        "event": "start",
        "message_id": message_id,
        "model": model_name,
    })

    try:
        async for chunk in model.astream(messages):
            if request is not None and await request.is_disconnected():
                logger.info("Client disconnected; aborting generation for %s", message_id)
                return

            delta = extract_text_delta(chunk)
            if delta:
                yield format_sse("token", {
                    "event": "token",
                    "delta": delta,
                })

    except asyncio.CancelledError:
        logger.info("Streaming task cancelled for message %s", message_id)
        return
    except Exception as exc:
        error_occurred = True
        logger.error(
            "Streaming error for message %s: %s",
            message_id,
            exc.__class__.__name__,
        )
        safe_message = sanitize_error_message(exc)
        yield format_sse("error", {
            "event": "error",
            "message": safe_message,
        })
        return

    if not error_occurred:
        yield format_sse("done", {
            "event": "done",
            "finish_reason": "stop",
        })


async def stream_generative_response(
    messages: List[BaseMessage],
    model: Any,
    model_name: str,
    request: Optional[Request] = None,
) -> AsyncIterator[str]:
    """Single-mode generative response stream combining prose and rich UI components.
    
    Emits events:
      - start: {"event": "start", "message_id": "...", "model": "..."}
      - status: {"event": "status", "status": "..."}
      - token: {"event": "token", "delta": "..."}
      - ui_component: {"event": "ui_component", "component": {...}, "block_id": "..."}
      - done: {"event": "done", "finish_reason": "stop"}
      - error: {"event": "error", "message": "..."}
    """
    message_id = str(uuid.uuid4())
    error_occurred = False

    yield format_sse("start", {
        "event": "start",
        "message_id": message_id,
        "model": model_name,
    })

    try:
        # Check whether model supports structured output planning
        if hasattr(model, "with_structured_output"):
            yield format_sse("status", {
                "event": "status",
                "status": "Analyzing request & planning adaptive UI...",
            })

            if request is not None and await request.is_disconnected():
                return

            plan = await generate_generative_plan(messages=messages, model=model)

            for block in plan.blocks:
                if request is not None and await request.is_disconnected():
                    return

                if block.type == "text":
                    # Stream prose tokens progressively
                    words = block.content.split(" ")
                    for i, word in enumerate(words):
                        if request is not None and await request.is_disconnected():
                            return
                        delta = word if i == len(words) - 1 else word + " "
                        yield format_sse("token", {
                            "event": "token",
                            "delta": delta,
                        })
                        if len(words) > 1:
                            await asyncio.sleep(0.005)
                elif block.type == "component":
                    # Emit validated UI component
                    block_id = str(uuid.uuid4())
                    yield format_sse("ui_component", {
                        "event": "ui_component",
                        "component": block.component.model_dump(),
                        "block_id": block_id,
                    })
        else:
            # Fallback to direct raw token streaming (preserves Phase 1 mock models)
            async for chunk in model.astream(messages):
                if request is not None and await request.is_disconnected():
                    return
                delta = extract_text_delta(chunk)
                if delta:
                    yield format_sse("token", {
                        "event": "token",
                        "delta": delta,
                    })

    except asyncio.CancelledError:
        logger.info("Generative stream cancelled for message %s", message_id)
        return
    except Exception as exc:
        error_occurred = True
        logger.error(
            "Generative streaming error for message %s: %s",
            message_id,
            exc.__class__.__name__,
        )
        safe_message = sanitize_error_message(exc)
        yield format_sse("error", {
            "event": "error",
            "message": safe_message,
        })
        return

    if not error_occurred:
        yield format_sse("done", {
            "event": "done",
            "finish_reason": "stop",
        })
