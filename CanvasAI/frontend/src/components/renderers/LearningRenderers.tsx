import React from 'react'
import { Check, X, CircleDot } from 'lucide-react'
import type {
  TimelineComponentSpec,
  StepsComponentSpec,
  ProsConsComponentSpec,
} from '../../types/uiPlan'

export const TimelineRenderer: React.FC<{ spec: TimelineComponentSpec }> = ({
  spec,
}) => {
  return (
    <div
      data-testid="rendered-timeline"
      className="p-5 rounded-2xl bg-white border border-slate-200 text-xs shadow-xs my-3"
    >
      <h4 className="font-semibold text-slate-900 text-sm mb-4">{spec.title}</h4>
      <div className="relative border-l border-slate-200 ml-3 space-y-6">
        {spec.steps.map((st, idx) => (
          <div key={idx} className="relative pl-6">
            <div className="absolute -left-2 top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-white border-2 border-emerald-500 text-emerald-600">
              <CircleDot size={10} />
            </div>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700 font-mono">
              {st.step}
            </span>
            <h5 className="font-semibold text-slate-900 text-xs mt-0.5 mb-1">{st.title}</h5>
            <p className="text-slate-600 leading-relaxed text-[11px]">{st.description}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

export const StepsRenderer: React.FC<{ spec: StepsComponentSpec }> = ({
  spec,
}) => {
  return (
    <div
      data-testid="rendered-steps"
      className="p-5 rounded-2xl bg-white border border-slate-200 text-xs shadow-xs my-3 space-y-4"
    >
      <h4 className="font-semibold text-slate-900 text-sm">{spec.title}</h4>
      <div className="space-y-3">
        {spec.items.map((it) => (
          <div
            key={it.step_number}
            className="flex items-start gap-3 p-3.5 rounded-xl bg-slate-50 border border-slate-200"
          >
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200 text-xs font-bold font-mono">
              {it.step_number}
            </div>
            <div>
              <h5 className="font-semibold text-slate-900 text-xs mb-1">{it.title}</h5>
              <p className="text-slate-600 leading-relaxed text-[11px]">{it.instruction}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export const ProsConsRenderer: React.FC<{ spec: ProsConsComponentSpec }> = ({
  spec,
}) => {
  return (
    <div
      data-testid="rendered-pros-cons"
      className="rounded-2xl bg-white border border-slate-200 overflow-hidden text-xs my-3 shadow-xs"
    >
      <div className="p-4 border-b border-slate-200 font-semibold text-slate-900 text-sm">
        {spec.title}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-slate-200">
        {/* Pros */}
        <div className="p-4 space-y-2 bg-emerald-50/40">
          <span className="text-xs font-semibold text-emerald-700 uppercase tracking-wider block mb-2">
            Advantages / Pros
          </span>
          <ul className="space-y-2">
            {spec.pros.map((pro, idx) => (
              <li key={idx} className="flex items-start gap-2 text-slate-700 text-xs leading-relaxed">
                <Check size={14} className="text-emerald-600 shrink-0 mt-0.5" />
                <span>{pro}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Cons */}
        <div className="p-4 space-y-2 bg-rose-50/40">
          <span className="text-xs font-semibold text-rose-700 uppercase tracking-wider block mb-2">
            Trade-offs / Cons
          </span>
          <ul className="space-y-2">
            {spec.cons.map((con, idx) => (
              <li key={idx} className="flex items-start gap-2 text-slate-700 text-xs leading-relaxed">
                <X size={14} className="text-rose-600 shrink-0 mt-0.5" />
                <span>{con}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
