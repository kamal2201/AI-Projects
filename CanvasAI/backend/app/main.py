from __future__ import annotations

import logging
from typing import Any, Optional
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.llm import convert_chat_messages, get_chat_model
from app.planning import generate_ui_plan
from app.schemas import (
    ChatMessage,
    ChatResponse,
    ChatStreamRequest,
    HealthResponse,
    UIPlan,
    UIPlanRequest,
)
from app.streaming import (
    format_sse,
    sanitize_error_message,
    stream_chat_response,
    stream_generative_response,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("canvas_ai")

app = FastAPI(
    title="CanvasAI Streaming & Planning API",
    description="True end-to-end response streaming and structured UI planning with LangChain and Google Gemini",
    version="1.1.0",
)

# Apply CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LLMService:
    """Service to create and manage LangChain LLM instances."""

    def get_chat_model(
        self,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        return get_chat_model(model_name=model_name, temperature=temperature)

    async def generate_ui_plan(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> UIPlan:
        """Invoke Gemini structured output to produce a validated UIPlan."""
        model = self.get_chat_model(model_name=model_name, temperature=temperature)
        return await generate_ui_plan(prompt=prompt, model=model)


def get_llm_service() -> LLMService:
    """FastAPI dependency for LLMService."""
    return LLMService()


@app.get("/health", response_model=HealthResponse)
async def health(cfg: Settings = Depends(get_settings)) -> HealthResponse:
    """Health check endpoint to verify backend status and active model."""
    return HealthResponse(
        status="ok",
        service="canvas-ai-backend",
        model=cfg.gemini_model,
    )


@app.post("/api/chat/stream")
async def chat_stream(
    body: ChatStreamRequest,
    request: Request,
    cfg: Settings = Depends(get_settings),
    llm_service: LLMService = Depends(get_llm_service),
):
    """Server-Sent Events streaming endpoint for chat completions.
    
    Adheres to the protocol:
      - start: {"event": "start", "message_id": "...", "model": "..."}
      - token: {"event": "token", "delta": "..."}
      - done:  {"event": "done", "finish_reason": "stop"}
      - error: {"event": "error", "message": "..."}
    """
    model_name = body.model or cfg.gemini_model
    langchain_messages = convert_chat_messages(body.messages)

    async def event_generator():
        try:
            model = llm_service.get_chat_model(
                model_name=model_name,
                temperature=body.temperature,
            )
        except Exception as exc:
            logger.error("Failed to initialize model: %s", exc.__class__.__name__)
            yield format_sse("start", {
                "event": "start",
                "message_id": "init-error",
                "model": model_name,
            })
            yield format_sse("error", {
                "event": "error",
                "message": sanitize_error_message(exc),
            })
            return

        async for sse_chunk in stream_generative_response(
            messages=langchain_messages,
            model=model,
            model_name=model_name,
            request=request,
        ):
            yield sse_chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat_non_streaming(
    body: ChatStreamRequest,
    cfg: Settings = Depends(get_settings),
    llm_service: LLMService = Depends(get_llm_service),
) -> ChatResponse:
    """Optional non-streaming endpoint for fallback/comparison."""
    model_name = body.model or cfg.gemini_model
    try:
        model = llm_service.get_chat_model(
            model_name=model_name,
            temperature=body.temperature,
        )
        langchain_messages = convert_chat_messages(body.messages)
        result = await model.ainvoke(langchain_messages)
        content = result.content if isinstance(result.content, str) else str(result.content)
        return ChatResponse(content=content, model=model_name)
    except Exception as exc:
        logger.error("Non-streaming chat error: %s", exc.__class__.__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=sanitize_error_message(exc),
        )


@app.post("/api/ui-plan", response_model=UIPlan)
async def create_ui_plan(
    body: UIPlanRequest,
    cfg: Settings = Depends(get_settings),
    llm_service: LLMService = Depends(get_llm_service),
) -> UIPlan:
    """Propose a structured UI plan matching the allowlisted component specifications.
    
    Invokes Gemini via LangChain's with_structured_output interface.
    """
    model_name = body.model or cfg.gemini_model
    try:
        plan = await llm_service.generate_ui_plan(
            prompt=body.prompt,
            model_name=model_name,
            temperature=body.temperature,
        )
        return plan
    except ValidationError as val_err:
        logger.warning("UI plan schema validation error: %s", val_err)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Proposed UI plan failed schema validation: {str(val_err)}",
        )
    except Exception as exc:
        logger.error("Error generating UI plan: %s", exc.__class__.__name__)
        safe_msg = sanitize_error_message(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_msg,
        )
