# CanvasAI — Adaptive Generative UI & Conversational Assistant

<p align="center">
  <img src="frontend/src/assets/hero.png" alt="CanvasAI Hero Banner" width="700" style="border-radius: 12px; max-width: 100%;" />
</p>

<p align="center">
  <strong>An intelligent conversational AI that seamlessly interleaves streaming prose with live, interactive UI components into a single unified conversation.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688.svg" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-19.3-61DAFB.svg" alt="React 19" />
  <img src="https://img.shields.io/badge/TypeScript-6.0+-3178C6.svg" alt="TypeScript" />
  <img src="https://img.shields.io/badge/LangChain-0.3+-green.svg" alt="LangChain" />
  <img src="https://img.shields.io/badge/Google%20Gemini-Powered-8E75C2.svg" alt="Google Gemini" />
  <img src="https://img.shields.io/badge/TailwindCSS-v4.3-38B2AC.svg" alt="Tailwind CSS" />
  <img src="https://img.shields.io/badge/Tests-74%20Passed-brightgreen.svg" alt="Tests" />
</p>

---

## 💡 Overview

**CanvasAI** is an adaptive, single-mode generative conversation platform inspired by ChatGPT's Intelligent UI. Instead of forcing users to switch between a pure text "Chat Mode" and a separate "Canvas / Design Mode", CanvasAI unifies text generation and rich interactive React components into **one continuous conversation feed with a single message composer**.

When you ask a question, Google Gemini (via LangChain's structured planning) dynamically plans and progressively streams:
- **Natural Markdown prose** for narrative explanations, tutorials, and summaries.
- **Rich, interactive UI components** (interactive charts, loan calculators, sortable data tables, Mermaid diagrams, regression playgrounds, KPI metrics, code blocks) rendered inline directly within the message bubble.

---

## 🏛️ Architecture

```
+-----------------------------------------------------------------------------------------+
|                                    React 19 Client                                      |
|  - Unified Generative Chat Feed (Prose + Adaptive Interactive UI Components)           |
|  - Real-Time Streaming Fetch Client & SSE Parser (token deltas + ui_component events)   |
|  - Component Registry & Safe Error Boundaries                                           |
|  - Developer UI Plan Inspector Drawer (Debug Tool)                                      |
+-----------------------------------------------------------------------------------------+
                         |                                          |
        POST /api/chat/stream (SSE)                        POST /api/ui-plan (JSON)
                         v                                          v
+-----------------------------------------------------------------------------------------+
|                                   FastAPI Backend                                       |
|  - POST /api/chat/stream: Generative streaming (status, tokens, ui_components, done)    |
|  - POST /api/ui-plan: LangChain with_structured_output(UIPlan) (Dev tool)               |
|  - GET /health: Health status & model verification                                      |
|  - Media Provider Interface: Verified HTTPS Image Provider                              |
+-----------------------------------------------------------------------------------------+
                                         |
                       LangChain ChatGoogleGenerativeAI
                                         |
                                         v
                         Google Gemini (gemini-3.5-flash-lite)
```

---

## ✨ Key Features

- **Single-Mode Generative Experience**: No mode toggle buttons or disjoint canvas windows. Every query produces an adaptive blend of text and interactive components tailored to the problem.
- **True End-to-End Streaming**: Real-time Server-Sent Events (SSE) deliver progressive status indicators, incremental prose tokens, and validated UI components as soon as they are ready.
- **19 Supported Component Specifications**: Comprehensive allowlist of UI components from KPI metric cards and financial calculators to Mermaid diagrams and linear regression playgrounds.
- **Multi-Turn Context & Continuity**: The assistant retains full conversational context across text and components, allowing follow-ups like *"Scale that recipe to 10 guests"* or *"Adjust the loan interest rate to 6.5%"*.
- **Safe Component Boundaries**: Every UI component is wrapped in a dedicated React Error Boundary, ensuring invalid component payloads fall back gracefully without crashing the chat session.
- **Developer UI Plan Inspector**: Top-right drawer allowing developers to inspect structured UI plans (`UIPlan`), raw JSON payloads, and validation details in real time.
- **Security by Design**: Enforces strict URL scheme validation (`https://` only; blocks `javascript:`, `data:`, `file:`), allowlisted action IDs for interactive controls, and sanitized error messages that never leak API keys or stack traces.

---

## 🧩 Component Catalogue (19 Supported Types)

| # | Component | Type Identifier | Description |
|---|---|---|---|
| 1 | **Card** | `card` | Formatted informational card with header and body text. |
| 2 | **Card Grid** | `card_grid` | Responsive grid grouping 1 to 6 cards. |
| 3 | **Metric** | `metric` | KPI card with formatted value, delta badge, trend indicator (`up`, `down`, `neutral`), and subtext. |
| 4 | **Chart** | `chart` | Recharts responsive visual charts (`bar`, `line`, `area`, `pie`, `scatter`) with tooltips and legends. |
| 5 | **Table** | `table` | Structured data table with clickable column sorting (ascending, descending, neutral). |
| 6 | **Code Block** | `code_block` | Syntax-highlighted code block with language badge and one-click copy button. |
| 7 | **Callout** | `callout` | Highlighted callout box with 4 variants (`info`, `warning`, `success`, `tip`). |
| 8 | **Expandable** | `expandable` | Disclosure panel with title, summary preview, and expandable full content. |
| 9 | **Accordion** | `accordion` | Collapsible accordion sections with open/close state. |
| 10 | **Tabs** | `tabs` | Interactive tabbed view with client-side active tab switching. |
| 11 | **Comparison** | `comparison` | Side-by-side feature comparison matrix between two entities. |
| 12 | **Pros & Cons** | `pros_cons` | Structured evaluation panel with pros and cons bullet lists. |
| 13 | **Timeline** | `timeline` | Milestone or chronological timeline with step nodes, titles, and descriptions. |
| 14 | **Steps** | `steps` | Numbered walkthrough tutorial instructions. |
| 15 | **Diagram** | `diagram` | Mermaid diagram syntax (flowcharts, sequence, class diagrams) rendered securely (`securityLevel: 'strict'`). |
| 16 | **Image** | `image` | Bounded, responsive image cards strictly enforcing secure `https://` URLs. |
| 17 | **Interactive Control** | `interactive_control` | Sliders, dropdowns, and buttons bound to an allowlist of safe action identifiers (`calculate`, `reset`, etc.). |
| 18 | **Calculator** | `calculator` | Interactive financial/numeric calculators (`loan`, `roi`, `savings`, `percentage`, `custom`) with live recalculation. |
| 19 | **Linear Regression** | `regression` | Interactive linear regression experiment with scatter points, slope/intercept sliders, best-fit line $ŷ = wx + b$, and residual analysis. |

---

## 📡 Streaming Wire Protocol

The `POST /api/chat/stream` SSE endpoint streams mixed text and validated UI components using a typed wire protocol:

| Event | Data Payload | Description |
| :--- | :--- | :--- |
| `start` | `{"event": "start", "message_id": "<uuid>", "model": "<model>"}` | Emitted immediately when generation starts; allocates the assistant message slot. |
| `status` | `{"event": "status", "status": "<text>"}` | Progress indicator (e.g., *"Analyzing request & planning adaptive UI..."*). |
| `token` | `{"event": "token", "delta": "<text>"}` | Incremental prose text delta rendered as live Markdown in real time. |
| `ui_component` | `{"event": "ui_component", "component": {...}, "block_id": "<uuid>"}` | Validated UI component specification emitted as soon as its data is ready. Rendered immediately inside the message bubble. |
| `image` | `{"event": "image", "url": "<url>", "alt": "<alt>", "caption": "..."}` | Verified media asset references. |
| `done` | `{"event": "done", "finish_reason": "stop"}` | Emitted upon successful stream completion. Marks generation complete. |
| `error` | `{"event": "error", "message": "<safe_msg>"}` | Emitted on errors. Never followed by `done`. Sanitizes credentials and internal stack traces. |

---

## 🗂️ Project Structure

```
CanvasAI/
├── .gitignore                      # Git ignore rules for CanvasAI
├── README.md                       # Main project documentation
├── backend/
│   ├── .env.example                # Example environment variables
│   ├── .gitignore                  # Backend-specific ignore rules
│   ├── .python-version             # Python version (3.12)
│   ├── README.md                   # Backend service documentation
│   ├── pyproject.toml              # UV / Python dependencies & configuration
│   ├── uv.lock                     # UV lockfile
│   ├── main.py                     # Entrypoint stub
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py               # Pydantic Settings & environment loader
│   │   ├── llm.py                  # LangChain ChatGoogleGenerativeAI setup & converters
│   │   ├── main.py                 # FastAPI application, CORS & endpoint routes
│   │   ├── media.py                # ImageProvider interface & URL validation
│   │   ├── planning.py             # System prompts & structured UI planning logic
│   │   ├── schemas.py              # Pydantic models for all 19 component specs
│   │   └── streaming.py            # SSE generator, token streaming & error sanitization
│   └── tests/
│       ├── test_health.py          # Health check endpoint test
│       ├── test_planning.py        # Schema validations & component discrimination
│       └── test_stream.py          # SSE event stream & cancellation tests
└── frontend/
    ├── .gitignore                  # Frontend-specific ignore rules
    ├── .oxlintrc.json              # Oxlint configuration
    ├── README.md                   # Frontend client documentation
    ├── index.html                  # HTML entry point
    ├── package.json                # NPM dependencies & scripts
    ├── package-lock.json           # NPM lockfile
    ├── tsconfig.json               # TypeScript project references
    ├── tsconfig.app.json           # Client TypeScript configuration
    ├── tsconfig.node.json          # Node TypeScript configuration
    ├── vite.config.ts              # Vite bundler configuration
    ├── public/
    │   ├── favicon.svg             # App favicon
    │   └── icons.svg               # SVG icon sprites
    └── src/
        ├── App.css                 # Application styles
        ├── App.tsx                 # Root React component
        ├── index.css               # Tailwind CSS imports & global rules
        ├── main.tsx                # React DOM entrypoint
        ├── assets/                 # Static assets (hero image, logos)
        ├── components/
        │   ├── ChatInput.tsx       # Message composer with stop/send controls
        │   ├── ChatInterface.tsx   # Chat state management & SSE handling
        │   ├── MessageItem.tsx     # Message bubble with prose + component renderers
        │   ├── MessageList.tsx     # Scrollable message history list
        │   ├── UIPlanInspector.tsx # Dev drawer for inspecting structured plans
        │   └── renderers/
        │       ├── ComponentRegistry.tsx     # Central component dispatcher & Error Boundary
        │       ├── DataRenderers.tsx         # Recharts charts and sortable data tables
        │       ├── InteractiveRenderers.tsx  # Calculators & interactive controls
        │       ├── LayoutRenderers.tsx       # Cards, card grids, tabs, accordions, comparisons
        │       ├── LearningRenderers.tsx     # Timelines, step guides, pros & cons
        │       ├── MediaAndDiagramRenderers.tsx # Mermaid diagrams & responsive images
        │       ├── RegressionRenderer.tsx    # Interactive linear regression playground
        │       └── TextAndCodeRenderers.tsx  # Code blocks, callouts, expandable panels
        ├── context/
        │   └── MessageComponentContext.tsx  # Context for component interactions
        ├── services/
        │   ├── chatStream.ts       # Streaming fetch client with abort support
        │   ├── sseParser.ts        # Robust Server-Sent Events parser
        │   └── uiPlanService.ts    # Service for invoking POST /api/ui-plan
        ├── test/
        │   ├── ChatInterface.test.tsx      # Chat UI and message flow tests
        │   ├── ComponentRegistry.test.tsx  # Render tests for all component types
        │   ├── UIPlanInspector.test.tsx    # Inspector drawer tests
        │   ├── chatStream.test.ts          # Client streaming unit tests
        │   ├── setup.ts                    # Test environment configuration
        │   ├── sseParser.test.ts           # SSE chunking & CRLF parsing tests
        │   └── uiPlanService.test.ts       # Structured output service tests
        └── types/
            ├── chat.ts             # Chat messages, SSE events & stream options
            └── uiPlan.ts           # TypeScript interfaces for all 19 UI components
```

---

## 🚀 Getting Started

### Prerequisites

- **Python**: 3.12 or newer
- **uv**: Fast Python package manager ([install instructions](https://docs.astral.sh/uv/))
- **Node.js**: 20+ and **npm**
- **Google Gemini API Key**: Obtain a key from [Google AI Studio](https://aistudio.google.com/app/apikey)

---

### 1. Backend Setup

1. Open a terminal and navigate to the backend directory:
   ```bash
   cd CanvasAI/backend
   ```

2. Create your `.env` configuration file from the template:
   ```bash
   cp .env.example .env
   ```

3. Open `.env` and insert your Google Gemini API key:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-3.5-flash-lite
   ```

4. Install dependencies and start the development server:
   ```bash
   uv run uvicorn app.main:app --reload --port 8000
   ```

5. Verify the backend is running:
   ```bash
   curl http://localhost:8000/health
   # Expected: {"status":"ok","service":"canvas-ai-backend","model":"gemini-3.5-flash-lite"}
   ```

---

### 2. Frontend Setup

1. In a new terminal, navigate to the frontend directory:
   ```bash
   cd CanvasAI/frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Launch the Vite development server:
   ```bash
   npm run dev
   ```

4. Open your browser and visit:
   ```
   http://localhost:5173
   ```

---

## 🧪 Testing & Verification

CanvasAI is thoroughly tested across both backend and frontend layers.

### Backend Tests (pytest)

Run the test suite using `uv`:
```bash
cd CanvasAI/backend
uv run pytest -v
```

Test coverage includes:
- Health check verification (`GET /health`)
- All 19 component schemas, discriminated union parsing, and boundary conditions
- URL security (HTTPS enforcement, malicious protocol rejection)
- SSE event streaming (`start`, `status`, `token`, `ui_component`, `done`, `error`)
- Request abort and client disconnect handling

```
collected 28 items
tests/test_health.py .                                                   [  3%]
tests/test_planning.py .................                                 [ 64%]
tests/test_stream.py ..........                                          [100%]
============================== 28 passed in 0.61s ==============================
```

---

### Frontend Tests (Vitest)

Run the Vitest test suite:
```bash
cd CanvasAI/frontend
npm run test
```

Test coverage includes:
- Single-mode unified conversation rendering without mode toggles
- Interleaved streaming prose and interactive UI components
- SSE parser (handling split network packets, multiline buffers, and CRLF normalization)
- All 19 component renderers, sortable tables, syntax-highlighted code blocks, and Mermaid diagrams
- SafeComponentBoundary error isolation
- Developer UI Plan Inspector drawer toggle and submission controls

```
Test Files  6 passed (6)
     Tests  46 passed (46)
  Duration  2.04s
```

---

### Frontend Production Build

Verify TypeScript types and produce an optimized production bundle:
```bash
cd CanvasAI/frontend
npm run build
```

---

## 🔒 Security & Resilience

1. **Protocol Validation**: All external image URLs strictly require `https://` or `http://localhost`. Dangerous protocols (`javascript:`, `data:`, `vbscript:`, `file:`) are rejected immediately by Pydantic validators.
2. **Action ID Allowlist**: Interactive controls (`interactive_control`) accept only predefined safe action identifiers:
   - `calculate`, `reset`, `filter_view`, `toggle_mode`, `export_summary`, `apply_settings`
3. **Safe Error Boundaries**: Any unexpected rendering error in a component is caught by `SafeComponentBoundary`, displaying a friendly fallback badge while keeping the rest of the chat functional.
4. **Credential Sanitization**: The streaming error handler inspects exceptions and sanitizes output, ensuring API keys, internal hosts, or raw stack traces are never exposed to the client.

---

## 📄 License

This project is licensed under the MIT License.
