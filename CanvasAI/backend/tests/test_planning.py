import math
from typing import Any, List
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.main import app, get_llm_service, LLMService
from app.schemas import (
    CalculatorComponent,
    CalloutComponent,
    CardComponent,
    ChartComponent,
    CodeBlockComponent,
    ImageComponent,
    InteractiveControlComponent,
    MetricComponent,
    RegressionComponent,
    RegressionPoint,
    TableComponent,
    UIPlan,
)
from app.planning import normalize_component_payload


class MockStructuredModel:
    """Mock model that implements with_structured_output."""

    def __init__(self, plan_to_return: Any = None, error_to_raise: Exception | None = None):
        self.plan_to_return = plan_to_return
        self.error_to_raise = error_to_raise
        self.received_messages: List[Any] = []

    def with_structured_output(self, schema: Any):
        outer = self

        class MockRunnableSequence:
            async def ainvoke(self, messages: Any):
                outer.received_messages = messages
                if outer.error_to_raise:
                    raise outer.error_to_raise
                return outer.plan_to_return

        return MockRunnableSequence()


class MockPlanningLLMService(LLMService):
    def __init__(self, mock_model: MockStructuredModel):
        self.mock_model = mock_model

    def get_chat_model(self, model_name=None, temperature=None):
        return self.mock_model


# -------------------------------------------------------------
# Unit Tests for Pydantic Schema Validations & Allowlist
# -------------------------------------------------------------

def test_card_component_schema_validation():
    card = CardComponent(title="Summary", body="Detailed summary content.")
    assert card.type == "card"
    assert card.title == "Summary"
    assert card.body == "Detailed summary content."

    # Blank title should fail
    with pytest.raises(ValidationError):
        CardComponent(title="", body="Content")


def test_chart_component_schema_validation():
    chart = ChartComponent(
        title="Revenue Growth",
        labels=["2022", "2023", "2024"],
        values=[100.5, 150.0, 230.2],
    )
    assert chart.type == "chart"
    assert len(chart.labels) == 3
    assert len(chart.values) == 3

    # Mismatched labels and values length must fail
    with pytest.raises(ValidationError):
        ChartComponent(title="Mismatch", labels=["A", "B"], values=[10.0])

    # Empty labels list must fail
    with pytest.raises(ValidationError):
        ChartComponent(title="Empty", labels=[], values=[])

    # Non-finite values (NaN / Inf) must fail
    with pytest.raises(ValidationError):
        ChartComponent(title="NaN", labels=["A"], values=[float("nan")])


def test_calculator_component_schema_validation():
    calc = CalculatorComponent(title="Mortgage Calculator", initial_value=250000.0)
    assert calc.type == "calculator"
    assert calc.initial_value == 250000.0

    # Non-finite initial_value must fail
    with pytest.raises(ValidationError):
        CalculatorComponent(title="Inf Calc", initial_value=float("inf"))


def test_regression_component_schema_and_normalization():
    # Direct schema validation
    pts = [RegressionPoint(x=1.0, y=2.0), RegressionPoint(x=2.0, y=4.0)]
    reg = RegressionComponent(title="Sample Fit", points=pts, initial_slope=2.0, initial_intercept=0.0)
    assert reg.type == "regression"
    assert len(reg.points) == 2
    assert reg.initial_slope == 2.0

    # Non-finite coordinates fail
    with pytest.raises(ValidationError):
        RegressionComponent(title="Bad", points=[RegressionPoint(x=float("nan"), y=1.0)])

    # Normalization with automatic OLS calculation
    normalized = normalize_component_payload(
        "regression",
        "Fitted Line",
        {"points": [{"x": 1, "y": 2}, {"x": 2, "y": 4}, {"x": 3, "y": 6}]},
    )
    assert isinstance(normalized, RegressionComponent)
    assert normalized.initial_slope == 2.0
    assert normalized.initial_intercept == 0.0


def test_table_normalization_from_dictionaries_and_numbers():
    normalized = normalize_component_payload(
        "table",
        "Performance",
        {
            "rows": [
                {"Model": "ResNet", "Accuracy": 92.5},
                {"Model": "ViT", "Accuracy": 95.1},
            ]
        },
    )
    assert isinstance(normalized, TableComponent)
    assert normalized.headers == ["Model", "Accuracy"]
    assert normalized.rows == [["ResNet", "92.5"], ["ViT", "95.1"]]


def test_metric_component_validation():
    metric = MetricComponent(label="MRR", value="$54,200", change="+18%", trend="up")
    assert metric.type == "metric"
    assert metric.label == "MRR"
    assert metric.trend == "up"


def test_table_component_validation():
    table = TableComponent(
        title="Comparison",
        headers=["Feature", "Pro", "Enterprise"],
        rows=[["SSO", "No", "Yes"], ["SLA", "99.9%", "99.99%"]],
    )
    assert table.type == "table"
    assert len(table.rows) == 2

    # Column count mismatch must fail
    with pytest.raises(ValidationError):
        TableComponent(
            title="Bad Table",
            headers=["A", "B"],
            rows=[["A", "B", "C"]],
        )


def test_code_block_component_validation():
    code = CodeBlockComponent(title="main.py", language="python", code="print('hello')")
    assert code.type == "code_block"
    assert code.language == "python"


def test_callout_component_validation():
    callout = CalloutComponent(title="Important", content="Take note of this", variant="warning")
    assert callout.type == "callout"
    assert callout.variant == "warning"


def test_image_component_security_validation():
    # HTTPS url must pass
    img = ImageComponent(url="https://images.unsplash.com/photo-1", alt="Diagram image")
    assert img.url.startswith("https://")

    # JavaScript URI must fail
    with pytest.raises(ValidationError):
        ImageComponent(url="javascript:alert(1)", alt="Hacked")

    # Insecure HTTP URL must fail
    with pytest.raises(ValidationError):
        ImageComponent(url="http://insecure.site/img.png", alt="Insecure")


def test_interactive_control_allowlist_validation():
    # Allowed action passes
    ctrl = InteractiveControlComponent(
        title="Recalculate",
        label="Recalculate Estimates",
        control_type="button",
        action_id="calculate",
    )
    assert ctrl.action_id == "calculate"

    # Arbitrary unapproved action_id fails
    with pytest.raises(ValidationError):
        InteractiveControlComponent(
            title="Dangerous",
            label="Execute Code",
            control_type="button",
            action_id="eval_arbitrary_js",
        )


def test_ui_plan_allowlist_enforcement():
    # Unsupported component type 'button' must fail discriminated union validation
    with pytest.raises(ValidationError):
        UIPlan.model_validate({
            "title": "Bad Plan",
            "explanation": "Trying unsupported button",
            "components": [{"type": "button", "label": "Submit"}],
        })

    # Excessive component count (> 8) must fail
    with pytest.raises(ValidationError):
        UIPlan.model_validate({
            "title": "Too Many",
            "explanation": "Over limits",
            "components": [
                {"type": "card", "title": f"Card {i}", "body": "Body text"}
                for i in range(10)
            ],
        })


def test_ui_plan_empty_components_allowed():
    # Empty components list is valid when plain text explanation is sufficient
    plan = UIPlan.model_validate({
        "title": "Text Only Explanation",
        "explanation": "No visual components are necessary for this simple query.",
        "components": [],
    })
    assert plan.title == "Text Only Explanation"
    assert len(plan.components) == 0


# -------------------------------------------------------------
# Integration Tests for POST /api/ui-plan Endpoint
# -------------------------------------------------------------

@pytest.mark.asyncio
async def test_ui_plan_endpoint_success_all_components():
    """Verify endpoint successfully returns validated plan with card, chart, and calculator."""
    expected_plan = UIPlan(
        title="Personal Finance Overview",
        explanation="A dashboard card, monthly spending chart, and savings calculator.",
        components=[
            CardComponent(title="Account Summary", body="Net assets: $45,000"),
            ChartComponent(
                title="Monthly Spending",
                labels=["Jan", "Feb", "Mar"],
                values=[1200.0, 1450.0, 1300.0],
            ),
            CalculatorComponent(title="Compound Savings", initial_value=5000.0),
        ],
    )

    mock_model = MockStructuredModel(plan_to_return=expected_plan)
    app.dependency_overrides[get_llm_service] = lambda: MockPlanningLLMService(mock_model)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/ui-plan",
                json={"prompt": "Show me a financial dashboard"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["title"] == "Personal Finance Overview"
            assert len(data["components"]) == 3
            assert data["components"][0]["type"] == "card"
            assert data["components"][1]["type"] == "chart"
            assert data["components"][2]["type"] == "calculator"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ui_plan_endpoint_empty_components():
    """Verify endpoint handles empty component list appropriately."""
    expected_plan = UIPlan(
        title="General Answer",
        explanation="A simple explanation that does not require rich components.",
        components=[],
    )

    mock_model = MockStructuredModel(plan_to_return=expected_plan)
    app.dependency_overrides[get_llm_service] = lambda: MockPlanningLLMService(mock_model)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/ui-plan",
                json={"prompt": "What is Python?"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["title"] == "General Answer"
            assert data["components"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ui_plan_endpoint_model_failure():
    """Verify endpoint returns safe 500 error when model invocation fails."""
    mock_model = MockStructuredModel(
        error_to_raise=RuntimeError("Google API 429 ResourceExhausted: Quota exceeded")
    )
    app.dependency_overrides[get_llm_service] = lambda: MockPlanningLLMService(mock_model)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/ui-plan",
                json={"prompt": "Trigger quota error"},
            )
            assert response.status_code == 500
            data = response.json()
            assert "detail" in data
            assert "rate limit or quota" in data["detail"].lower()
            assert "429" not in data["detail"]  # sanitized
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ui_plan_endpoint_validation_error():
    """Verify 422 Unprocessable Entity when request body has invalid prompt."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Prompt cannot be empty
        response = await client.post("/api/ui-plan", json={"prompt": ""})
        assert response.status_code == 422
