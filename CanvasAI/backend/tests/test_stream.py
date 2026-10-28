import asyncio
import json
from typing import Any, AsyncIterator, List, Optional
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessageChunk, HumanMessage, AIMessage, SystemMessage

from app.main import app, get_llm_service, LLMService
from app.llm import convert_chat_messages, extract_text_delta
from app.schemas import ChatMessage
from app.streaming import format_sse, stream_chat_response


class MockLangChainModel:
    """Mock LangChain chat model that simulates astream() behavior."""

    def __init__(self, chunks: List[Any], delay: float = 0.0, raise_after: Optional[int] = None):
        self.chunks = chunks
        self.delay = delay
        self.raise_after = raise_after
        self.received_messages: List[Any] = []

    async def astream(self, messages: List[Any]) -> AsyncIterator[AIMessageChunk]:
        self.received_messages = messages
        for idx, item in enumerate(self.chunks):
            if self.raise_after is not None and idx == self.raise_after:
                raise RuntimeError("Simulated Gemini connection drop")
            if self.delay > 0:
                await asyncio.sleep(self.delay)
            if isinstance(item, AIMessageChunk):
                yield item
            else:
                yield AIMessageChunk(content=item)


class MockLLMService(LLMService):
    """Mock service returning a controlled mock model."""

    def __init__(self, model: Any):
        self.model = model

    def get_chat_model(
        self,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        return self.model


def parse_sse_events(sse_text: str) -> List[dict]:
    """Helper to parse raw SSE text stream into structured events."""
    events = []
    blocks = sse_text.strip().split("\n\n")
    for block in blocks:
        if not block.strip():
            continue
        event_name = "message"
        data_lines = []
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[7:].strip()
            elif line.startswith("data: "):
                data_lines.append(line[6:].strip())
        raw_data = "\n".join(data_lines)
        parsed_data = {}
        if raw_data:
            try:
                parsed_data = json.loads(raw_data)
            except Exception:
                parsed_data = {"raw": raw_data}
        events.append({"event": event_name, "data": parsed_data})
    return events


@pytest.mark.asyncio
async def test_extract_text_delta_variations():
    """Verify safe text delta extraction across various chunk structures."""
    # Simple string
    assert extract_text_delta(AIMessageChunk(content="Hello ")) == "Hello "
    # Empty string
    assert extract_text_delta(AIMessageChunk(content="")) == ""
    # List of strings
    assert extract_text_delta(AIMessageChunk(content=["Hello", " ", "World"])) == "Hello World"
    # List of content dicts with text
    assert (
        extract_text_delta(AIMessageChunk(content=[{"type": "text", "text": "Streaming"}]))
        == "Streaming"
    )
    # None or non-text
    assert extract_text_delta(None) == ""
    assert extract_text_delta(AIMessageChunk(content=[])) == ""


@pytest.mark.asyncio
async def test_convert_chat_messages_preserves_history():
    """Verify conversion of user, assistant, and system messages into LangChain messages."""
    input_msgs = [
        ChatMessage(role="system", content="You are a helpful coding assistant."),
        ChatMessage(role="user", content="How do I stream responses in FastAPI?"),
        ChatMessage(role="assistant", content="Use StreamingResponse with SSE."),
        ChatMessage(role="user", content="Show me an example."),
    ]
    converted = convert_chat_messages(input_msgs)
    assert len(converted) == 4
    assert isinstance(converted[0], SystemMessage)
    assert converted[0].content == "You are a helpful coding assistant."
    assert isinstance(converted[1], HumanMessage)
    assert converted[1].content == "How do I stream responses in FastAPI?"
    assert isinstance(converted[2], AIMessage)
    assert converted[2].content == "Use StreamingResponse with SSE."
    assert isinstance(converted[3], HumanMessage)
    assert converted[3].content == "Show me an example."


@pytest.mark.asyncio
async def test_stream_chat_incremental_tokens():
    """Verify incremental arrival of tokens and proper start/token/done event sequence."""
    chunks = ["Hello", ", ", "this ", "is ", "streaming!"]
    mock_model = MockLangChainModel(chunks=chunks)

    app.dependency_overrides[get_llm_service] = lambda: MockLLMService(mock_model)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat/stream",
                json={
                    "messages": [{"role": "user", "content": "Stream to me!"}],
                    "model": "gemini-2.5-flash",
                },
            )
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            assert response.headers.get("x-accel-buffering") == "no"

            events = parse_sse_events(response.text)
            assert len(events) >= 3

            # First event must be 'start'
            assert events[0]["event"] == "start"
            assert "message_id" in events[0]["data"]
            assert events[0]["data"]["model"] == "gemini-2.5-flash"

            # Intermediate events must be 'token'
            token_events = [e for e in events if e["event"] == "token"]
            assert len(token_events) == len(chunks)
            accumulated = "".join(e["data"]["delta"] for e in token_events)
            assert accumulated == "Hello, this is streaming!"

            # Final event must be 'done'
            assert events[-1]["event"] == "done"
            assert events[-1]["data"]["finish_reason"] == "stop"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_chat_error_during_generation():
    """Verify that an error mid-stream emits 'error' and NEVER emits 'done'."""
    chunks = ["Initial part", "second part", "should not reach"]
    mock_model = MockLangChainModel(chunks=chunks, raise_after=2)

    app.dependency_overrides[get_llm_service] = lambda: MockLLMService(mock_model)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat/stream",
                json={"messages": [{"role": "user", "content": "Trigger error"}]},
            )
            assert response.status_code == 200
            events = parse_sse_events(response.text)

            # Assert 'start' was emitted
            assert events[0]["event"] == "start"

            # Assert tokens prior to error were emitted
            token_events = [e for e in events if e["event"] == "token"]
            assert len(token_events) == 2

            # Assert last event is 'error'
            error_events = [e for e in events if e["event"] == "error"]
            assert len(error_events) == 1
            assert "message" in error_events[0]["data"]
            assert not error_events[0]["data"]["message"].startswith("Traceback")

            # CRUCIAL: Must NOT emit 'done' event after an error
            done_events = [e for e in events if e["event"] == "done"]
            assert len(done_events) == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_chat_client_cancellation():
    """Verify that client disconnection cancels stream generation gracefully."""
    class FakeDisconnectedRequest:
        def __init__(self, disconnect_after_step: int):
            self.step = 0
            self.disconnect_after_step = disconnect_after_step

        async def is_disconnected(self) -> bool:
            self.step += 1
            return self.step > self.disconnect_after_step

    fake_request = FakeDisconnectedRequest(disconnect_after_step=2)
    chunks = ["Token 1", "Token 2", "Token 3", "Token 4", "Token 5"]
    mock_model = MockLangChainModel(chunks=chunks)

    yielded_chunks = []
    async for sse_chunk in stream_chat_response(
        messages=[HumanMessage(content="Hi")],
        model=mock_model,
        model_name="gemini-2.5-flash",
        request=fake_request,  # type: ignore
    ):
        yielded_chunks.append(sse_chunk)

    parsed = parse_sse_events("".join(yielded_chunks))
    tokens = [p for p in parsed if p["event"] == "token"]
    # Should stop early due to disconnect, without raising unhandled exception
    assert len(tokens) <= 3
    # No done event if disconnected mid-stream
    assert not any(p["event"] == "done" for p in parsed)


@pytest.mark.asyncio
async def test_stream_empty_model_response():
    """Verify proper handling when model emits no tokens (e.g. empty content)."""
    mock_model = MockLangChainModel(chunks=["", ""])
    app.dependency_overrides[get_llm_service] = lambda: MockLLMService(mock_model)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat/stream",
                json={"messages": [{"role": "user", "content": "Say nothing"}]},
            )
            assert response.status_code == 200
            events = parse_sse_events(response.text)
            assert len(events) == 2
            assert events[0]["event"] == "start"
            assert events[1]["event"] == "done"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_init_failure_yields_error():
    """Verify that a failure during model initialization cleanly yields start and error events."""
    class FailingLLMService(LLMService):
        def get_chat_model(self, model_name=None, temperature=None):
            raise ValueError("GEMINI_API_KEY is not configured.")

    app.dependency_overrides[get_llm_service] = lambda: FailingLLMService()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat/stream",
                json={"messages": [{"role": "user", "content": "Hello"}]},
            )
            assert response.status_code == 200
            events = parse_sse_events(response.text)
            assert len(events) == 2
            assert events[0]["event"] == "start"
            assert events[1]["event"] == "error"
            assert "API key" in events[1]["data"]["message"]
            assert not any(e["event"] == "done" for e in events)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_non_streaming():
    """Verify optional non-streaming chat endpoint."""
    class AinvokeMockModel:
        async def ainvoke(self, messages):
            return AIMessage(content="Non-streaming response")

    app.dependency_overrides[get_llm_service] = lambda: MockLLMService(AinvokeMockModel())

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Hello"}]},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["role"] == "assistant"
            assert data["content"] == "Non-streaming response"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_chat_generative_mixed_blocks():
    """Verify single-mode stream emits start, status, tokens, ui_component, and done events."""
    from app.schemas import GenerativeResponsePlan, TextBlock, ComponentBlock, MetricComponent

    plan = GenerativeResponsePlan(
        summary="Sunday roast plan",
        blocks=[
            TextBlock(content="Here is your roast dinner plan:"),
            ComponentBlock(
                component=MetricComponent(
                    label="Cooking Time",
                    value="3 hrs 30 mins",
                    change="Low & slow",
                    trend="neutral",
                )
            ),
            TextBlock(content="Next, prepare the side dishes."),
        ],
    )

    class MockStructuredGenerativeModel:
        def with_structured_output(self, schema):
            class Seq:
                async def ainvoke(self, messages):
                    return plan
            return Seq()

    app.dependency_overrides[get_llm_service] = lambda: MockLLMService(
        MockStructuredGenerativeModel()
    )

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat/stream",
                json={"messages": [{"role": "user", "content": "Plan sunday roast"}]},
            )
            assert response.status_code == 200
            events = parse_sse_events(response.text)

            # Assert event sequence
            event_types = [e["event"] for e in events]
            assert "start" in event_types
            assert "status" in event_types
            assert "token" in event_types
            assert "ui_component" in event_types
            assert "done" in event_types

            # Check ui_component payload
            ui_events = [e for e in events if e["event"] == "ui_component"]
            assert len(ui_events) == 1
            assert ui_events[0]["data"]["component"]["type"] == "metric"
            assert ui_events[0]["data"]["component"]["label"] == "Cooking Time"

            # Check tokens accumulated content
            token_events = [e for e in events if e["event"] == "token"]
            accumulated_text = "".join(e["data"]["delta"] for e in token_events)
            assert "Here is your roast dinner plan:" in accumulated_text
            assert "Next, prepare the side dishes." in accumulated_text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stream_validation_error():
    """Verify 422 Unprocessable Entity when request body has empty messages list."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/chat/stream", json={"messages": []})
        assert response.status_code == 422
