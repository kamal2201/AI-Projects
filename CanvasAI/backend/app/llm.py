from __future__ import annotations

import logging
from typing import Any, List, Optional
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings
from app.schemas import ChatMessage

logger = logging.getLogger(__name__)


def convert_chat_messages(messages: List[ChatMessage]) -> List[BaseMessage]:
    """Convert API ChatMessage models to LangChain message instances."""
    langchain_messages: List[BaseMessage] = []
    for msg in messages:
        role = msg.role.lower()
        if role == "user":
            langchain_messages.append(HumanMessage(content=msg.content))
        elif role == "assistant":
            langchain_messages.append(AIMessage(content=msg.content))
        elif role == "system":
            langchain_messages.append(SystemMessage(content=msg.content))
        else:
            langchain_messages.append(HumanMessage(content=msg.content))
    return langchain_messages


def extract_text_delta(chunk: Any) -> str:
    """Safely extract text delta from a streaming message chunk."""
    if chunk is None:
        return ""

    content = getattr(chunk, "content", chunk)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts: List[str] = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") == "text" and "text" in part:
                    text_parts.append(str(part["text"]))
                elif "text" in part:
                    text_parts.append(str(part["text"]))
            elif hasattr(part, "text"):
                text_parts.append(str(getattr(part, "text", "")))
        return "".join(text_parts)

    return ""


def get_chat_model(
    model_name: Optional[str] = None,
    temperature: Optional[float] = None,
    api_key: Optional[str] = None,
) -> ChatGoogleGenerativeAI:
    """Instantiate ChatGoogleGenerativeAI using configuration settings."""
    settings = get_settings()
    effective_key = api_key or settings.effective_api_key
    if not effective_key:
        raise ValueError(
            "GEMINI_API_KEY is not configured. Please set GEMINI_API_KEY or GOOGLE_API_KEY."
        )

    selected_model = model_name or settings.gemini_model
    selected_temp = temperature if temperature is not None else settings.temperature

    model_kwargs: dict[str, Any] = {
        "model": selected_model,
        "google_api_key": effective_key,
    }
    # Only supply temperature if explicitly provided; otherwise use model's default
    if selected_temp is not None:
        model_kwargs["temperature"] = selected_temp

    return ChatGoogleGenerativeAI(**model_kwargs)
