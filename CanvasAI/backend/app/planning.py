from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, List, Literal, Optional
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, TypeAdapter

from app.schemas import (
    CardComponent,
    ComponentBlock,
    GenerativeBlock,
    GenerativeResponsePlan,
    RegressionComponent,
    RegressionPoint,
    TextBlock,
    UIComponent,
    UIPlan,
)

logger = logging.getLogger(__name__)

UI_PLAN_SYSTEM_PROMPT = """You are CanvasAI, an expert UI planning assistant.
Your task is to analyze the user's request and propose a clean, structured UI Plan composed ONLY of supported component specifications from the allowlist.

Component Catalogue (ALLOWLIST ONLY):
1. 'card': Title and textual body content.
2. 'card_grid': Grid container grouping 1-6 simple cards.
3. 'metric': KPI metric card with label, value (e.g. '$54k', '99.9%'), optional trend ('up'|'down'|'neutral'), and change indicator.
4. 'chart': Visual data chart with 'title', 'chart_type' ('bar'|'line'|'area'|'pie'|'scatter'), 'labels', and numeric 'values'.
5. 'table': Structured data table with 'title', 'headers' (column names), and 'rows' (lists of strings matching headers count).
6. 'code_block': Syntax-highlighted code with 'language', 'code', and optional 'title'.
7. 'callout': Rich text callout box with 'title', 'content', and 'variant' ('info'|'warning'|'success'|'tip').
8. 'expandable': Disclosure panel with 'title', 'summary', and detailed 'content'.
9. 'accordion': Collapsible accordion items with 'title' and 'items' (title, content).
10. 'tabs': Interactive tabbed view with 'title' and 'items' (label, content).
11. 'comparison': Side-by-side comparison between 'item_a_name' and 'item_b_name' with feature list.
12. 'pros_cons': Structured analysis with 'title', 'pros' (list of strings), and 'cons' (list of strings).
13. 'timeline': Chronological or milestone timeline with 'steps' (step, title, description).
14. 'steps': Step-by-step ordered tutorial walkthrough with 'items' (step_number, title, instruction).
15. 'diagram': Mermaid diagram syntax (flowchart, sequenceDiagram, classDiagram) with 'title' and 'syntax'.
16. 'image': Image presentation with 'url' (MUST use https://), 'alt' text, and optional 'caption'.
17. 'interactive_control': Slider, dropdown, or action button with 'title', 'label', 'control_type', and 'action_id' from allowlist ('calculate', 'reset', 'filter_view', 'toggle_mode', 'export_summary', 'apply_settings').
18. 'calculator': Financial/numeric calculator with 'title', 'calculator_type' ('custom'|'loan'|'roi'|'savings'|'percentage'), and 'initial_value'.
19. 'regression': Interactive linear regression experiment with scatter points, model line yHat = w*x + b, slope/intercept sliders, and residual analysis.

Component Selection Guidelines:
- Linear regression, curve fitting, scatter plots -> ALWAYS use 'regression' with numeric points [{'x': ..., 'y': ...}], initial_slope, and initial_intercept. NEVER use a bar chart for linear regression.
- Numerical data, distributions or trends -> Use 'chart' (bar/line/pie) and 'metric' KPI cards.
- Multi-dimensional data, tabular comparisons -> Use 'table'.
- Architecture, flowcharts, or processes -> Use 'diagram' (mermaid) or 'timeline'.
- Straightforward factual question -> Return an empty components list; plain explanation is sufficient.
- NEVER fabricate sources or output raw JSON strings as body text.
"""

GENERATIVE_PLAN_SYSTEM_PROMPT = """You are CanvasAI, an intelligent conversational AI inspired by ChatGPT's Intelligent UI.
Your role is to produce ONE cohesive, single-mode adaptive response combining natural prose with the most appropriate interactive and visual components.

Every response is an adaptive interface structured as an ordered sequence of 'blocks':
- 'text': Markdown formatted text prose, explanations, headings, equations, or summaries. Set type='text', text='...'.
- 'component': A validated UI component. Set type='component', component_type='...', title='...', props={...}.

Allowed Component Types:
1. 'regression': Interactive linear regression model. props: {'points': [{'x': 1, 'y': 2}, {'x': 2, 'y': 3.8}], 'initial_slope': 1.8, 'initial_intercept': 0.2, 'x_label': 'X', 'y_label': 'Y'}. Use whenever regression, scatter fitting, or machine learning lines are requested.
2. 'card': Overview card. props: {'body': '...'}
3. 'card_grid': Grid of cards. props: {'items': [{'title': '...', 'body': '...'}]}
4. 'metric': KPI card. props: {'label': '...', 'value': '$54k', 'change': '+12%', 'trend': 'up'}
5. 'chart': Visual chart. props: {'chart_type': 'bar'|'line'|'area'|'pie'|'scatter', 'labels': ['A', 'B'], 'values': [10, 20]}
6. 'table': Data table. props: {'headers': ['Col1', 'Col2'], 'rows': [['Val1', 'Val2']]}
7. 'code_block': Syntax-highlighted code. props: {'language': 'python', 'code': '...'}
8. 'callout': Highlighted note. props: {'variant': 'info'|'warning'|'success'|'tip', 'content': '...'}
9. 'expandable': Disclosure panel. props: {'summary': '...', 'content': '...'}
10. 'accordion': Collapsible sections. props: {'items': [{'title': '...', 'content': '...'}]}
11. 'tabs': Tabbed view. props: {'items': [{'label': '...', 'content': '...'}]}
12. 'comparison': Side-by-side table. props: {'item_a_name': 'A', 'item_b_name': 'B', 'features': [{'name': 'F', 'item_a_val': '...', 'item_b_val': '...'}]}
13. 'pros_cons': Pros and cons. props: {'pros': ['...'], 'cons': ['...']}
14. 'timeline': Timeline milestones. props: {'steps': [{'step': '10:00 AM', 'title': '...', 'description': '...'}]}
15. 'steps': Numbered tutorial steps. props: {'items': [{'step_number': 1, 'title': '...', 'instruction': '...'}]}
16. 'diagram': Mermaid diagram. props: {'syntax': 'graph TD\\nA-->B'}
17. 'interactive_control': Slider or button. props: {'control_type': 'slider'|'button'|'dropdown', 'label': '...', 'action_id': 'calculate'|'reset'|'filter_view'}
18. 'calculator': Numeric tool. props: {'calculator_type': 'loan'|'roi'|'savings'|'percentage'|'custom', 'initial_value': 1000}

Adaptive Rules:
- For linear regression or line-of-best-fit: ALWAYS use 'regression'. Do not use a bar chart. Format equations cleanly as yHat = w * x + b or ŷ = wx + b.
- Simple factual question ("What is 2+2?"): Return a single 'text' block.
- For structured tables: ONLY provide a 'table' if you have meaningful multi-column records. NEVER create empty tables or placeholder rows.
- NEVER leak raw backend JSON or internal data structures into the text prose.
"""

class UIBlockSpec(BaseModel):
    type: Literal["text", "component"] = Field(
        ..., description="Block type: 'text' for prose, or 'component' for UI widgets"
    )
    text: Optional[str] = Field(
        default=None, description="Markdown prose text content when type is 'text'"
    )
    component_type: Optional[str] = Field(
        default=None, description="Component type from allowlist"
    )
    title: Optional[str] = Field(default=None, description="Component title")
    props: Optional[Dict[str, Any]] = Field(
        default=None, description="Component attributes (e.g. body, labels, values, headers, rows, items, value)"
    )

class UIBlockPlan(BaseModel):
    summary: Optional[str] = Field(None, description="Brief summary of plan")
    blocks: List[UIBlockSpec] = Field(default_factory=list, description="Ordered sequence of text and components")


def normalize_component_payload(
    comp_type: str,
    title: Optional[str],
    props: Optional[Dict[str, Any]],
) -> UIComponent:
    """Normalize model props and strictly validate against Pydantic discriminated union schemas."""
    data = dict(props or {})
    data["type"] = comp_type.lower()
    if "title" not in data or not data["title"]:
        data["title"] = title or "Overview"

    # 1. Linear regression normalization
    is_regression = (
        data["type"] in ("regression", "linear_regression")
        or "regression" in (title or "").lower()
        or "regression" in str(data.get("title", "")).lower()
        or (data["type"] == "chart" and data.get("chart_type") in ("scatter", "regression"))
    )

    if is_regression:
        data["type"] = "regression"
        raw_pts = data.get("points") or []
        if not raw_pts and "labels" in data and "values" in data:
            try:
                raw_pts = [{"x": float(l), "y": float(v)} for l, v in zip(data["labels"], data["values"])]
            except (ValueError, TypeError):
                raw_pts = []
        if not raw_pts and "x" in data and "y" in data and isinstance(data["x"], list) and isinstance(data["y"], list):
            raw_pts = [{"x": float(xi), "y": float(yi)} for xi, yi in zip(data["x"], data["y"])]

        clean_pts = []
        for p in raw_pts:
            if isinstance(p, dict) and "x" in p and "y" in p:
                try:
                    px, py = float(p["x"]), float(p["y"])
                    if math.isfinite(px) and math.isfinite(py):
                        clean_pts.append({"x": px, "y": py})
                except (ValueError, TypeError):
                    pass

        if len(clean_pts) < 2:
            clean_pts = [
                {"x": 1.0, "y": 2.2},
                {"x": 2.0, "y": 3.9},
                {"x": 3.0, "y": 6.1},
                {"x": 4.0, "y": 8.0},
                {"x": 5.0, "y": 10.3},
            ]
        data["points"] = clean_pts

        # Calculate exact Least-Squares fit for initial slope/intercept if not present
        n = len(clean_pts)
        mean_x = sum(p["x"] for p in clean_pts) / n
        mean_y = sum(p["y"] for p in clean_pts) / n
        denom = sum((p["x"] - mean_x) ** 2 for p in clean_pts)
        if denom > 0:
            ols_slope = sum((p["x"] - mean_x) * (p["y"] - mean_y) for p in clean_pts) / denom
            ols_intercept = mean_y - ols_slope * mean_x
            if data.get("initial_slope") is None:
                data["initial_slope"] = round(ols_slope, 3)
            if data.get("initial_intercept") is None:
                data["initial_intercept"] = round(ols_intercept, 3)

    # 2. Table normalization
    elif data["type"] == "table":
        headers = data.get("headers") or []
        raw_rows = data.get("rows") or []
        if raw_rows and isinstance(raw_rows[0], dict):
            if not headers:
                headers = list(raw_rows[0].keys())
            formatted_rows = [[str(r.get(h, "")) for h in headers] for r in raw_rows]
        elif raw_rows and isinstance(raw_rows[0], (list, tuple)):
            if not headers:
                headers = [f"Col {i+1}" for i in range(len(raw_rows[0]))]
            col_count = len(headers)
            formatted_rows = []
            for r in raw_rows:
                row_strs = [str(cell) for cell in r]
                if len(row_strs) < col_count:
                    row_strs += [""] * (col_count - len(row_strs))
                elif len(row_strs) > col_count:
                    row_strs = row_strs[:col_count]
                formatted_rows.append(row_strs)
        else:
            raise ValueError("Table component must have non-empty rows of structured data")

        if not formatted_rows or all(not any(cell.strip() for cell in row) for row in formatted_rows):
            raise ValueError("Table rows cannot be empty")

        data["headers"] = [str(h) for h in headers]
        data["rows"] = formatted_rows

    # 3. Chart normalization
    elif data["type"] == "chart":
        labels = data.get("labels") or []
        values = data.get("values") or []
        if not labels or not values or len(labels) != len(values):
            m = min(len(labels), len(values))
            if m > 0:
                data["labels"] = [str(l) for l in labels[:m]]
                data["values"] = [float(v) for v in values[:m]]
            else:
                data["labels"] = ["A", "B", "C"]
                data["values"] = [10.0, 20.0, 30.0]
        else:
            data["labels"] = [str(l) for l in labels]
            data["values"] = [float(v) for v in values]

    # 4. Metric normalization
    elif data["type"] == "metric":
        if "label" not in data or not data["label"]:
            data["label"] = title or "Metric"
        if "value" not in data or not data["value"]:
            data["value"] = str(data.get("val", "0"))

    # 5. Calculator normalization
    elif data["type"] == "calculator":
        if "initial_value" in data:
            data["initial_value"] = float(data["initial_value"])

    return TypeAdapter(UIComponent).validate_python(data)


async def generate_ui_plan(
    prompt: str,
    model: Any,
) -> UIPlan:
    """Invoke model with structured output to produce a validated UIPlan (Phase 2 preserved)."""
    messages = [
        SystemMessage(content=UI_PLAN_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    structured_llm = model.with_structured_output(UIPlan)
    raw_result = await structured_llm.ainvoke(messages)

    if isinstance(raw_result, UIPlan):
        return raw_result

    if isinstance(raw_result, dict):
        return UIPlan.model_validate(raw_result)

    raise ValueError(f"Unexpected response type from structured model: {type(raw_result)}")


async def generate_generative_plan(
    messages: List[BaseMessage],
    model: Any,
) -> GenerativeResponsePlan:
    """Invoke model to produce an ordered sequence of prose text and adaptive UI components."""
    planning_messages = [
        SystemMessage(content=GENERATIVE_PLAN_SYSTEM_PROMPT),
        *messages,
    ]

    structured_llm = model.with_structured_output(UIBlockPlan)
    raw_result = await structured_llm.ainvoke(planning_messages)

    raw_blocks: List[UIBlockSpec] = []
    summary: Optional[str] = None

    if isinstance(raw_result, UIBlockPlan):
        raw_blocks = raw_result.blocks
        summary = raw_result.summary
    elif isinstance(raw_result, dict):
        parsed = UIBlockPlan.model_validate(raw_result)
        raw_blocks = parsed.blocks
        summary = parsed.summary
    elif isinstance(raw_result, GenerativeResponsePlan):
        return raw_result

    validated_blocks: List[GenerativeBlock] = []
    for b in raw_blocks:
        if b.type == "text" and b.text and b.text.strip():
            content = b.text.strip()
            # If the LLM output raw JSON inside text, prevent raw JSON leakage
            if content.startswith("{") and content.endswith("}"):
                try:
                    parsed_json = json.loads(content)
                    if isinstance(parsed_json, dict) and ("type" in parsed_json or "component_type" in parsed_json):
                        c_type = parsed_json.get("type") or parsed_json.get("component_type")
                        comp = normalize_component_payload(c_type, parsed_json.get("title"), parsed_json)
                        validated_blocks.append(ComponentBlock(component=comp))
                        continue
                except Exception:
                    pass
            validated_blocks.append(TextBlock(content=content))
        elif b.type == "component" and b.component_type:
            try:
                comp = normalize_component_payload(b.component_type, b.title, b.props)
                validated_blocks.append(ComponentBlock(component=comp))
            except Exception as e:
                logger.warning("Failed to normalize component '%s': %s", b.component_type, e)
                # NEVER leak str(b.props) or raw JSON! Only convert if clean prose text exists.
                raw_text = (b.props or {}).get("body") or (b.props or {}).get("content") or (b.props or {}).get("explanation")
                if raw_text and isinstance(raw_text, str) and not raw_text.strip().startswith("{"):
                    validated_blocks.append(TextBlock(content=raw_text.strip()))

    if not validated_blocks:
        validated_blocks.append(TextBlock(content="I processed your request."))

    return GenerativeResponsePlan(summary=summary, blocks=validated_blocks)
