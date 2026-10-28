# CanvasAI Frontend

Interactive React 19 + TypeScript frontend for CanvasAI, providing a unified single-mode generative UI conversation experience with real-time SSE streaming.

## Features

- **Unified Single-Mode Feed**: Prose and rich UI components live in a single conversation history with one message composer.
- **Real-Time Streaming Fetch Client**: Consumes Server-Sent Events (`start`, `status`, `token`, `ui_component`, `done`, `error`) and updates messages incrementally.
- **Component Registry**: 19 custom React component renderers spanning cards, grids, Recharts charts, sortable data tables, Mermaid diagrams, financial calculators, and linear regression playgrounds.
- **Safe Component Boundaries**: React Error Boundaries wrap each component renderer to isolate errors and prevent chat crashes.
- **Developer UI Plan Inspector**: Slide-over drawer for developers to test and inspect raw structured `UIPlan` outputs from Google Gemini.

## Tech Stack

- **React 19** & **TypeScript**
- **Vite** with Tailwind CSS v4
- **Recharts** for charts and data visualization
- **Mermaid** for diagrams and flowcharts
- **React-Markdown** with KaTeX math rendering (`remark-math`, `rehype-katex`, `remark-gfm`)
- **Lucide React** for icons
- **Vitest** & **React Testing Library** for automated testing

## Setup & Running

### Requirements
- Node.js 20+
- npm

### Installation & Development

1. Navigate to the frontend directory:
   ```bash
   cd CanvasAI/frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Start the Vite development server:
   ```bash
   npm run dev
   ```

4. Open `http://localhost:5173` in your browser.

## Scripts

- `npm run dev`: Starts Vite dev server.
- `npm run build`: Type-checks with TypeScript and compiles production bundle.
- `npm run test`: Runs test suite with Vitest.
- `npm run lint`: Runs Oxlint.
- `npm run preview`: Locally previews the production build.
