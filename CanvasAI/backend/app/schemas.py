from __future__ import annotations

import math
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


RoleType = Literal["user", "assistant", "system"]


class ChatMessage(BaseModel):
    role: RoleType = Field(..., description="Role of the message sender")
    content: str = Field(..., description="Content of the message")


class ChatStreamRequest(BaseModel):
    messages: List[ChatMessage] = Field(
        ..., min_length=1, description="Conversation history including latest user message"
    )
    model: Optional[str] = Field(
        default=None, description="Optional override for Gemini model"
    )
    temperature: Optional[float] = Field(
        default=None, ge=0.0, le=2.0, description="Sampling temperature"
    )


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "canvas-ai-backend"
    model: str


class ChatResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str
    model: str


# =========================================================================
# Phase 2 & 2.5: Rich Component Catalogue Schemas (Discriminated Union)
# =========================================================================

def validate_https_url(url: str) -> str:
    """Ensure URLs only use safe https:// or localhost schemes."""
    cleaned = url.strip()
    if not (cleaned.startswith("https://") or cleaned.startswith("http://localhost")):
        raise ValueError("URL must use https:// protocol")
    lower = cleaned.lower()
    for forbidden in ["javascript:", "data:", "vbscript:", "file:"]:
        if forbidden in lower:
            raise ValueError(f"Unsafe URL scheme '{forbidden}' is strictly prohibited")
    return cleaned


# --- A. Rich Text & Code Components ---

class CodeBlockComponent(BaseModel):
    """Syntax-highlighted code block with language and copy action."""
    type: Literal["code_block"] = Field(default="code_block")
    title: Optional[str] = Field(None, max_length=120, description="Optional title or file name")
    language: str = Field(
        default="text", max_length=30, description="Programming language identifier"
    )
    code: str = Field(..., min_length=1, max_length=4000, description="Source code text")


class CalloutComponent(BaseModel):
    """Highlighted callout, quote or citation block."""
    type: Literal["callout"] = Field(default="callout")
    title: str = Field(..., min_length=1, max_length=120, description="Callout header")
    content: str = Field(..., min_length=1, max_length=1500, description="Callout message body")
    variant: Literal["info", "warning", "success", "tip"] = Field(
        default="info", description="Visual styling accent"
    )


class ExpandableComponent(BaseModel):
    """Expandable disclosure panel for long-form detailed explanations."""
    type: Literal["expandable"] = Field(default="expandable")
    title: str = Field(..., min_length=1, max_length=120, description="Collapsed header prompt")
    summary: str = Field(..., min_length=1, max_length=300, description="Brief preview summary")
    content: str = Field(..., min_length=1, max_length=2500, description="Full detailed explanation")


# --- B. Layout & Organization Components ---

class CardComponent(BaseModel):
    """Standard informational card (Phase 2 preserved)."""
    type: Literal["card"] = Field(default="card", description="Component identifier")
    title: str = Field(..., min_length=1, max_length=120, description="Card title")
    body: str = Field(..., min_length=1, max_length=2000, description="Textual body content")


class CardGridComponent(BaseModel):
    """Grid layout grouping multiple cards together."""
    type: Literal["card_grid"] = Field(default="card_grid")
    title: Optional[str] = Field(None, max_length=120, description="Optional grid header")
    items: List[CardComponent] = Field(
        ..., min_length=1, max_length=6, description="List of 1 to 6 cards inside grid"
    )


class MetricComponent(BaseModel):
    """Numeric KPI card with badge, trend indicator, and subtext."""
    type: Literal["metric"] = Field(default="metric")
    label: str = Field(..., min_length=1, max_length=100, description="Metric label")
    value: str = Field(..., min_length=1, max_length=50, description="Main formatted metric value")
    change: Optional[str] = Field(None, max_length=30, description="Delta percentage or diff")
    trend: Optional[Literal["up", "down", "neutral"]] = Field(
        None, description="Trend direction for badge accent"
    )
    subtext: Optional[str] = Field(None, max_length=150, description="Secondary description")


class AccordionItem(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=1500)


class AccordionComponent(BaseModel):
    """Collapsible accordion sections with active state."""
    type: Literal["accordion"] = Field(default="accordion")
    title: Optional[str] = Field(None, max_length=120)
    items: List[AccordionItem] = Field(..., min_length=1, max_length=10)


class TabItem(BaseModel):
    label: str = Field(..., min_length=1, max_length=60)
    content: str = Field(..., min_length=1, max_length=1500)


class TabsComponent(BaseModel):
    """Interactive tabbed panel with working switch state."""
    type: Literal["tabs"] = Field(default="tabs")
    title: Optional[str] = Field(None, max_length=120)
    items: List[TabItem] = Field(..., min_length=1, max_length=8)


# --- C. Data Visualization Components ---

class ChartSeries(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    values: List[float] = Field(..., min_length=1, max_length=20)


class ChartComponent(BaseModel):
    """Responsive visual data chart (Bar, Line, Area, Pie, Scatter)."""
    type: Literal["chart"] = Field(default="chart", description="Component identifier")
    title: str = Field(..., min_length=1, max_length=120, description="Chart title")
    chart_type: Literal["bar", "line", "area", "pie", "scatter"] = Field(
        default="bar", description="Visual chart presentation type"
    )
    labels: List[str] = Field(
        ..., min_length=1, max_length=20, description="Category or time-series labels"
    )
    values: List[float] = Field(
        ..., min_length=1, max_length=20, description="Corresponding numeric values"
    )
    series: Optional[List[ChartSeries]] = Field(
        None, max_length=5, description="Optional multi-series data"
    )

    @model_validator(mode="after")
    def validate_chart_data(self) -> ChartComponent:
        if len(self.labels) != len(self.values):
            raise ValueError(
                f"Number of chart labels ({len(self.labels)}) must equal number of values ({len(self.values)})"
            )
        for label in self.labels:
            if not label.strip():
                raise ValueError("Chart labels cannot be empty strings")
            if len(label) > 60:
                raise ValueError(f"Chart label '{label[:20]}...' exceeds maximum length of 60 characters")
        for val in self.values:
            if not math.isfinite(val):
                raise ValueError("Chart values must be finite numbers (no NaN or infinity)")

        if self.series:
            for s in self.series:
                if len(s.values) != len(self.labels):
                    raise ValueError(f"Series '{s.name}' values length must match labels length")
                for sv in s.values:
                    if not math.isfinite(sv):
                        raise ValueError("Series values must be finite numbers")
        return self


class TableComponent(BaseModel):
    """Structured data table with columns and rows."""
    type: Literal["table"] = Field(default="table")
    title: str = Field(..., min_length=1, max_length=120, description="Table title")
    headers: List[str] = Field(..., min_length=1, max_length=10, description="Column header titles")
    rows: List[List[str]] = Field(..., min_length=1, max_length=50, description="Grid data rows")

    @model_validator(mode="after")
    def validate_table_structure(self) -> TableComponent:
        col_count = len(self.headers)
        for r_idx, row in enumerate(self.rows):
            if len(row) != col_count:
                raise ValueError(
                    f"Table row {r_idx} column count ({len(row)}) does not match headers count ({col_count})"
                )
        return self


# --- D. Diagrams & Media Components ---

class DiagramComponent(BaseModel):
    """Mermaid diagram specification (flowcharts, sequence diagrams)."""
    type: Literal["diagram"] = Field(default="diagram")
    title: str = Field(..., min_length=1, max_length=120, description="Diagram caption/title")
    syntax: str = Field(..., min_length=1, max_length=2500, description="Mermaid diagram definition")
    caption: Optional[str] = Field(None, max_length=200, description="Optional explanatory footer")


class ImageComponent(BaseModel):
    """Bounded, responsive image card with safe URL validation."""
    type: Literal["image"] = Field(default="image")
    url: str = Field(..., min_length=1, max_length=500, description="HTTPS image URL")
    alt: str = Field(..., min_length=1, max_length=200, description="Accessibility alt text")
    caption: Optional[str] = Field(None, max_length=200, description="Optional caption text")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        return validate_https_url(v)


# --- E. Interactive Controls & Calculators ---

SAFE_ACTION_ALLOWLIST = {
    "calculate",
    "reset",
    "filter_view",
    "toggle_mode",
    "export_summary",
    "apply_settings",
}

class InteractiveControlComponent(BaseModel):
    """Interactive control (slider, dropdown, or action button) linked only to allowlisted actions."""
    type: Literal["interactive_control"] = Field(default="interactive_control")
    title: str = Field(..., min_length=1, max_length=120)
    control_type: Literal["slider", "dropdown", "button"] = Field(default="button")
    label: str = Field(..., min_length=1, max_length=80)
    action_id: str = Field(
        ...,
        description="Explicit safe action identifier from allowlist",
    )
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    default_val: Optional[float] = None
    options: Optional[List[str]] = Field(None, max_length=10)

    @field_validator("action_id")
    @classmethod
    def check_action(cls, v: str) -> str:
        if v not in SAFE_ACTION_ALLOWLIST:
            raise ValueError(f"action_id '{v}' is not in the safe allowlist: {list(SAFE_ACTION_ALLOWLIST)}")
        return v


class CalculatorComponent(BaseModel):
    """Interactive numeric calculator tool (Phase 2 preserved and enhanced)."""
    type: Literal["calculator"] = Field(default="calculator", description="Component identifier")
    title: str = Field(..., min_length=1, max_length=120, description="Title of calculator")
    calculator_type: Literal["custom", "loan", "roi", "savings", "percentage"] = Field(
        default="custom", description="Predefined calculation formula logic"
    )
    initial_value: float = Field(default=0.0, description="Starting primary numeric value")
    rate: Optional[float] = Field(None, description="Optional percentage or interest rate")
    term: Optional[float] = Field(None, description="Optional term in years/months")
    unit: Optional[str] = Field(default="$", max_length=10, description="Currency or measurement unit")

    @model_validator(mode="after")
    def validate_calculator_data(self) -> CalculatorComponent:
        if not math.isfinite(self.initial_value):
            raise ValueError("Calculator initial_value must be a finite number")
        if self.rate is not None and not math.isfinite(self.rate):
            raise ValueError("Calculator rate must be a finite number")
        if self.term is not None and not math.isfinite(self.term):
            raise ValueError("Calculator term must be a finite number")
        return self


# --- F. Structured Learning & Comparison Experiences ---

class ComparisonFeature(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    item_a_val: str = Field(..., min_length=1, max_length=120)
    item_b_val: str = Field(..., min_length=1, max_length=120)


class ComparisonComponent(BaseModel):
    """Side-by-side feature comparison panel."""
    type: Literal["comparison"] = Field(default="comparison")
    title: str = Field(..., min_length=1, max_length=120)
    item_a_name: str = Field(..., min_length=1, max_length=80)
    item_b_name: str = Field(..., min_length=1, max_length=80)
    features: List[ComparisonFeature] = Field(..., min_length=1, max_length=12)


class ProsConsComponent(BaseModel):
    """Structured Pros vs. Cons panel."""
    type: Literal["pros_cons"] = Field(default="pros_cons")
    title: str = Field(..., min_length=1, max_length=120)
    pros: List[str] = Field(..., min_length=1, max_length=10)
    cons: List[str] = Field(..., min_length=1, max_length=10)


class TimelineStep(BaseModel):
    step: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)


class TimelineComponent(BaseModel):
    """Chronological or milestone timeline."""
    type: Literal["timeline"] = Field(default="timeline")
    title: str = Field(..., min_length=1, max_length=120)
    steps: List[TimelineStep] = Field(..., min_length=1, max_length=12)


class StepItem(BaseModel):
    step_number: int = Field(..., ge=1, le=20)
    title: str = Field(..., min_length=1, max_length=100)
    instruction: str = Field(..., min_length=1, max_length=600)


class StepsComponent(BaseModel):
    """Step-by-step tutorial or onboarding walkthrough."""
    type: Literal["steps"] = Field(default="steps")
    title: str = Field(..., min_length=1, max_length=120)
    items: List[StepItem] = Field(..., min_length=1, max_length=12)


# --- G. Mathematical & Scientific Visualizations ---

class RegressionPoint(BaseModel):
    x: float = Field(..., description="Feature input coordinate (x)")
    y: float = Field(..., description="Observed output target (y)")

    @model_validator(mode="after")
    def validate_finite(self) -> RegressionPoint:
        if not (math.isfinite(self.x) and math.isfinite(self.y)):
            raise ValueError("Regression point coordinates must be finite numbers")
        return self


class RegressionComponent(BaseModel):
    """Interactive linear regression visualization with scatter points, fitted line, and residual analysis."""
    type: Literal["regression"] = Field(default="regression", description="Component identifier")
    title: str = Field(..., min_length=1, max_length=120, description="Title of the regression chart")
    description: Optional[str] = Field(None, max_length=500, description="Optional dataset description or problem context")
    points: List[RegressionPoint] = Field(..., min_length=2, max_length=100, description="Observed scatter data points")
    initial_slope: Optional[float] = Field(None, description="Initial slope parameter (w) for yHat = w*x + b")
    initial_intercept: Optional[float] = Field(None, description="Initial intercept parameter (b) for yHat = w*x + b")
    x_label: Optional[str] = Field(default="X (Feature)", max_length=60, description="Horizontal axis title")
    y_label: Optional[str] = Field(default="Y (Target)", max_length=60, description="Vertical axis title")
    show_residuals: Optional[bool] = Field(default=True, description="Whether vertical residual segments are shown")
    allow_fit: Optional[bool] = Field(default=True, description="Whether to provide least-squares fit button")


# =========================================================================
# Discriminated Union & Top-Level Plan
# =========================================================================

UIComponent = Annotated[
    Union[
        CardComponent,
        CardGridComponent,
        ChartComponent,
        TableComponent,
        MetricComponent,
        CalculatorComponent,
        CodeBlockComponent,
        CalloutComponent,
        ExpandableComponent,
        AccordionComponent,
        TabsComponent,
        ComparisonComponent,
        ProsConsComponent,
        TimelineComponent,
        StepsComponent,
        DiagramComponent,
        ImageComponent,
        InteractiveControlComponent,
        RegressionComponent,
    ],
    Field(discriminator="type"),
]


# =========================================================================
# Phase 3: Generative Content Blocks & Single-Mode Response Plan
# =========================================================================

class TextBlock(BaseModel):
    """Prose text block supporting full Markdown formatting."""
    type: Literal["text"] = Field(default="text")
    content: str = Field(..., min_length=1, max_length=10000, description="Markdown prose content")


class ComponentBlock(BaseModel):
    """Structured rich UI component block."""
    type: Literal["component"] = Field(default="component")
    component: UIComponent = Field(..., description="Validated allowlisted UI component specification")


GenerativeBlock = Annotated[
    Union[TextBlock, ComponentBlock],
    Field(discriminator="type"),
]


class GenerativeResponsePlan(BaseModel):
    """Ordered sequence of prose and adaptive interactive UI components."""
    summary: Optional[str] = Field(None, max_length=200, description="Optional brief response summary")
    blocks: List[GenerativeBlock] = Field(
        default_factory=list,
        max_length=12,
        description="Ordered sequence of text prose and rich interactive UI components",
    )


class UIPlan(BaseModel):
    """Structured UI Plan proposed by Gemini with rich component catalogue."""
    title: str = Field(
        ..., min_length=1, max_length=150, description="High-level descriptive title of the UI plan"
    )
    explanation: str = Field(
        ..., min_length=1, max_length=1000, description="Concise explanation of the UI proposal"
    )
    components: List[UIComponent] = Field(
        default_factory=list,
        max_length=8,
        description="List of proposed UI components from the allowlisted catalogue",
    )


class UIPlanRequest(BaseModel):
    """Request payload for proposing a UI plan."""
    prompt: str = Field(
        ..., min_length=1, max_length=3000, description="User prompt describing requirements for the UI"
    )
    model: Optional[str] = Field(
        default=None, description="Optional override for Gemini model"
    )
    temperature: Optional[float] = Field(
        default=None, ge=0.0, le=2.0, description="Sampling temperature for the plan generation"
    )
