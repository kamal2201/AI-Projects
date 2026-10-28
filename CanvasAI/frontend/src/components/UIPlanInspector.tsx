import React, { useState, useRef } from 'react'
import {
  Code,
  Loader2,
  Send,
  AlertCircle,
  Copy,
  Check,
  RotateCcw,
  Sparkles,
  Info,
  LayoutGrid,
} from 'lucide-react'
import type { UIPlan } from '../types/uiPlan'
import { fetchUIPlan } from '../services/uiPlanService'
import { renderComponent } from './renderers/ComponentRegistry'

const SAMPLE_PROMPTS = [
  'Create a SaaS pricing dashboard with plan comparisons, monthly revenue chart, and an ROI savings calculator.',
  'Show a project health overview card with quarterly bug velocity chart and devops metrics.',
  'Explain how binary search trees work with a Mermaid flowchart and step-by-step instructions.',
]

export const UIPlanInspector: React.FC = () => {
  const [prompt, setPrompt] = useState('')
  const [plan, setPlan] = useState<UIPlan | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [displayMode, setDisplayMode] = useState<'rendered' | 'json'>('rendered')
  const abortControllerRef = useRef<AbortController | null>(null)

  const handleSubmit = async (promptText: string) => {
    const textToSubmit = promptText.trim()
    if (!textToSubmit || isLoading) return

    setError(null)
    setPlan(null)
    setIsLoading(true)

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const result = await fetchUIPlan(
        { prompt: textToSubmit },
        controller.signal
      )
      setPlan(result)
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setError('UI plan generation was cancelled.')
        return
      }
      const message =
        err instanceof Error ? err.message : 'Failed to generate UI plan.'
      setError(message)
    } finally {
      setIsLoading(false)
      abortControllerRef.current = null
    }
  }

  const handleCopyJSON = async () => {
    if (!plan) return
    try {
      await navigator.clipboard.writeText(
        JSON.stringify(plan.components, null, 2)
      )
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard write might fail in some sandbox environments
    }
  }

  const handleReset = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    setPlan(null)
    setError(null)
    setPrompt('')
  }

  return (
    <div
      data-testid="ui-plan-inspector"
      className="flex flex-1 flex-col overflow-y-auto px-6 py-6 max-w-5xl mx-auto w-full space-y-6"
    >
      {/* Intro Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider rounded bg-purple-950/60 text-purple-300 border border-purple-800/50">
              Phase 2.5 Component Catalogue
            </span>
            <h2 className="text-lg font-bold text-slate-100">
              Structured UI Plan & Canvas Inspector
            </h2>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Tests Gemini’s structured output via LangChain&apos;s{' '}
            <code className="text-purple-300 bg-purple-950/40 px-1 py-0.5 rounded text-[11px]">
              with_structured_output(UIPlan)
            </code>{' '}
            and renders dynamic components across all catalogue categories.
          </p>
        </div>

        {(plan || error) && (
          <button
            type="button"
            data-testid="reset-plan-button"
            onClick={handleReset}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 px-3 py-1.5 rounded-lg border border-slate-800 bg-slate-900/60 hover:bg-slate-800 transition-colors"
          >
            <RotateCcw size={13} />
            Reset
          </button>
        )}
      </div>

      {/* Input Form */}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          handleSubmit(prompt)
        }}
        className="space-y-3"
      >
        <label
          htmlFor="plan-prompt-input"
          className="block text-xs font-semibold text-slate-300 uppercase tracking-wider"
        >
          User Prompt for UI Planning:
        </label>
        <div className="relative rounded-xl bg-slate-900 border border-slate-800 focus-within:border-purple-500 transition-colors">
          <textarea
            id="plan-prompt-input"
            data-testid="plan-prompt-input"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={isLoading}
            placeholder="Describe what UI you need (e.g. 'Show monthly expenses with breakdown chart, comparisons, and savings calculator')..."
            rows={3}
            className="w-full resize-none bg-transparent p-3.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none"
          />
          <div className="flex items-center justify-between border-t border-slate-800/80 px-3 py-2 bg-slate-950/40">
            <span className="text-[11px] text-slate-500">
              Allowlisted: card, chart, table, metric, code, callout, accordion, tabs, comparison, pros/cons, timeline, steps, diagram, image, calculator
            </span>
            <button
              type="submit"
              data-testid="generate-plan-button"
              disabled={!prompt.trim() || isLoading}
              className="flex items-center gap-2 px-4 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:hover:bg-purple-600 text-white text-xs font-semibold shadow-md transition-all"
            >
              {isLoading ? (
                <>
                  <Loader2 size={13} className="animate-spin" />
                  Generating Plan...
                </>
              ) : (
                <>
                  <Send size={13} />
                  Propose UI Plan
                </>
              )}
            </button>
          </div>
        </div>

        {/* Sample presets */}
        {!plan && !isLoading && (
          <div className="space-y-1.5 pt-1">
            <span className="text-[11px] text-slate-500 font-medium block">
              Or pick an example prompt:
            </span>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              {SAMPLE_PROMPTS.map((sample) => (
                <button
                  key={sample}
                  type="button"
                  onClick={() => {
                    setPrompt(sample)
                    handleSubmit(sample)
                  }}
                  className="text-left p-2.5 rounded-lg bg-slate-900/60 border border-slate-800/80 hover:border-purple-600/50 hover:bg-slate-800/40 text-slate-300 text-xs transition-colors"
                >
                  <Sparkles size={12} className="text-purple-400 mb-1 inline mr-1" />
                  {sample}
                </button>
              ))}
            </div>
          </div>
        )}
      </form>

      {/* Loading state */}
      {isLoading && (
        <div
          data-testid="plan-loading-state"
          className="flex flex-col items-center justify-center p-12 text-center rounded-2xl bg-slate-900/40 border border-slate-800/60"
        >
          <div className="relative mb-3">
            <div className="h-10 w-10 rounded-full border-2 border-purple-500/30 border-t-purple-400 animate-spin" />
          </div>
          <span className="text-sm font-medium text-slate-200">
            Invoking Gemini with structured output schema...
          </span>
          <span className="text-xs text-slate-500 mt-1">
            Validating proposed components against Pydantic schema
          </span>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div
          data-testid="plan-error-banner"
          className="p-4 rounded-xl bg-red-950/40 border border-red-800/60 text-red-200 text-xs flex items-start gap-3"
        >
          <AlertCircle size={18} className="text-red-400 shrink-0 mt-0.5" />
          <div className="flex-1">
            <span className="font-semibold block text-red-300 mb-0.5">
              UI Plan Generation Error
            </span>
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Plan Result View */}
      {plan && !isLoading && (
        <div data-testid="plan-result-container" className="space-y-5 animate-in fade-in duration-300">
          {/* Plan Header Card */}
          <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 space-y-3">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400 bg-emerald-950/60 border border-emerald-800/50 px-2.5 py-0.5 rounded-full">
                <Check size={12} />
                Validated UIPlan
              </span>

              {/* View Switcher: Rendered Canvas vs JSON Spec */}
              <div className="flex items-center p-0.5 rounded-lg bg-slate-950 border border-slate-800 text-xs">
                <button
                  type="button"
                  data-testid="view-toggle-rendered"
                  onClick={() => setDisplayMode('rendered')}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-md font-medium transition-colors ${
                    displayMode === 'rendered'
                      ? 'bg-purple-600 text-white'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <LayoutGrid size={13} />
                  Rendered UI Canvas
                </button>
                <button
                  type="button"
                  data-testid="view-toggle-json"
                  onClick={() => setDisplayMode('json')}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-md font-medium transition-colors ${
                    displayMode === 'json'
                      ? 'bg-purple-600 text-white'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Code size={13} />
                  JSON Spec
                </button>
              </div>
            </div>

            <div>
              <h3
                data-testid="plan-title"
                className="text-lg font-bold text-slate-100"
              >
                {plan.title}
              </h3>
              <p
                data-testid="plan-explanation"
                className="text-sm text-slate-300 mt-1.5 leading-relaxed bg-slate-950/60 p-3 rounded-lg border border-slate-800/60"
              >
                {plan.explanation}
              </p>
            </div>

            {/* Component type pills */}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <span className="text-xs text-slate-500 font-medium">
                Components:
              </span>
              {plan.components.length === 0 ? (
                <span className="text-xs text-slate-400 italic flex items-center gap-1">
                  <Info size={12} />
                  No visual components proposed (text-only explanation is sufficient)
                </span>
              ) : (
                plan.components.map((comp, idx) => {
                  const compTitle = (comp as any).title || (comp as any).label || ''
                  return (
                    <span
                      key={`${comp.type}-${idx}`}
                      className="text-xs px-2.5 py-0.5 rounded-full font-medium border bg-slate-800/80 text-purple-300 border-purple-800/50"
                    >
                      {comp.type}{compTitle ? `: \u201C${compTitle}\u201D` : ''}
                    </span>
                  )
                })
              )}
            </div>
          </div>

          {/* Rendered Canvas Mode */}
          {displayMode === 'rendered' && (
            <div
              data-testid="rendered-canvas-container"
              className="space-y-4"
            >
              {plan.components.length === 0 ? (
                <div className="p-8 text-center rounded-2xl bg-slate-900 border border-slate-800 text-slate-400 text-sm">
                  This plan contains no visual components. The textual explanation above provides the complete response.
                </div>
              ) : (
                plan.components.map((comp, idx) => renderComponent(comp, idx))
              )}
            </div>
          )}

          {/* JSON Specification Viewer Mode (also always present in DOM or toggled) */}
          <div
            className={`rounded-2xl bg-slate-900 border border-slate-800 overflow-hidden ${
              displayMode === 'json' ? 'block' : 'hidden'
            }`}
          >
            <div className="flex items-center justify-between px-4 py-2.5 bg-slate-950/80 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Code size={14} className="text-purple-400" />
                <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                  Component Specifications (JSON)
                </span>
              </div>
              <button
                type="button"
                data-testid="copy-json-button"
                onClick={handleCopyJSON}
                className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors px-2 py-1 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800"
              >
                {copied ? (
                  <>
                    <Check size={12} className="text-emerald-400" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy size={12} />
                    Copy JSON
                  </>
                )}
              </button>
            </div>

            <pre
              data-testid="plan-json-viewer"
              className="p-4 text-xs font-mono text-purple-200 overflow-x-auto max-h-96 leading-relaxed bg-slate-950/40"
            >
              {JSON.stringify(plan.components, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
