import React, { useState } from 'react'
import {
  Copy,
  Check,
  Info,
  AlertTriangle,
  CheckCircle2,
  Lightbulb,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import type {
  CodeBlockComponentSpec,
  CalloutComponentSpec,
  ExpandableComponentSpec,
} from '../../types/uiPlan'

export const CodeBlockRenderer: React.FC<{ spec: CodeBlockComponentSpec }> = ({
  spec,
}) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(spec.code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // ignore clipboard error
    }
  }

  return (
    <div
      data-testid="rendered-code-block"
      className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden text-xs my-3 shadow-md"
    >
      <div className="flex items-center justify-between px-4 py-2 bg-slate-950 border-b border-slate-800 text-slate-400 font-mono text-[11px]">
        <span>{spec.title || spec.language || 'code'}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 hover:text-slate-200 transition-colors px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check size={12} className="text-emerald-400" />
              <span className="text-emerald-400">Copied</span>
            </>
          ) : (
            <>
              <Copy size={12} />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="p-4 overflow-x-auto font-mono text-emerald-300 leading-relaxed max-h-80">
        <code>{spec.code}</code>
      </pre>
    </div>
  )
}

export const CalloutRenderer: React.FC<{ spec: CalloutComponentSpec }> = ({
  spec,
}) => {
  const variant = spec.variant || 'info'

  const styles = {
    info: 'bg-blue-50 border-blue-200 text-blue-900',
    warning: 'bg-amber-50 border-amber-200 text-amber-900',
    success: 'bg-emerald-50 border-emerald-200 text-emerald-900',
    tip: 'bg-purple-50 border-purple-200 text-purple-900',
  }[variant]

  const IconComponent = {
    info: Info,
    warning: AlertTriangle,
    success: CheckCircle2,
    tip: Lightbulb,
  }[variant]

  return (
    <div
      data-testid="rendered-callout"
      className={`p-4 rounded-xl border flex gap-3 text-xs my-3 ${styles}`}
    >
      <IconComponent size={18} className="shrink-0 mt-0.5" />
      <div>
        <h4 className="font-semibold text-sm mb-1">{spec.title}</h4>
        <p className="leading-relaxed opacity-90">{spec.content}</p>
      </div>
    </div>
  )
}

export const ExpandableRenderer: React.FC<{ spec: ExpandableComponentSpec }> = ({
  spec,
}) => {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <div
      data-testid="rendered-expandable"
      className="rounded-xl bg-white border border-slate-200 overflow-hidden my-3 text-xs shadow-xs"
    >
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-slate-50 transition-colors"
      >
        <div>
          <h4 className="font-semibold text-slate-900 text-sm">{spec.title}</h4>
          <p className="text-slate-500 text-xs mt-0.5">{spec.summary}</p>
        </div>
        <div className="p-1 rounded bg-slate-100 text-slate-600 ml-4 shrink-0">
          {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </button>

      {isOpen && (
        <div className="p-4 border-t border-slate-200 bg-slate-50/50 text-slate-700 leading-relaxed">
          {spec.content}
        </div>
      )}
    </div>
  )
}
