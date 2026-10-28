import React, { useState } from 'react'
import {
  TrendingUp,
  TrendingDown,
  Minus,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import type {
  CardComponentSpec,
  CardGridComponentSpec,
  MetricComponentSpec,
  TabsComponentSpec,
  AccordionComponentSpec,
  ComparisonComponentSpec,
} from '../../types/uiPlan'

export const CardRenderer: React.FC<{ spec: CardComponentSpec }> = ({
  spec,
}) => {
  return (
    <div
      data-testid="rendered-card"
      className="p-5 rounded-2xl bg-white border border-slate-200 text-xs shadow-xs my-3"
    >
      <h4 className="font-semibold text-slate-900 text-sm mb-2">{spec.title}</h4>
      <p className="text-slate-600 leading-relaxed whitespace-pre-wrap">{spec.body}</p>
    </div>
  )
}

export const CardGridRenderer: React.FC<{ spec: CardGridComponentSpec }> = ({
  spec,
}) => {
  return (
    <div data-testid="rendered-card-grid" className="my-3 space-y-2">
      {spec.title && (
        <h4 className="font-semibold text-slate-800 text-sm mb-1">{spec.title}</h4>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {spec.items.map((card, idx) => (
          <div
            key={idx}
            className="p-4 rounded-xl bg-white border border-slate-200 text-xs shadow-xs"
          >
            <h5 className="font-semibold text-slate-900 mb-1.5 text-xs">{card.title}</h5>
            <p className="text-slate-600 leading-relaxed text-[11px]">{card.body}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

export const MetricRenderer: React.FC<{ spec: MetricComponentSpec }> = ({
  spec,
}) => {
  return (
    <div
      data-testid="rendered-metric"
      className="p-5 rounded-2xl bg-white border border-slate-200 text-xs shadow-xs my-3 flex flex-col justify-between"
    >
      <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">
        {spec.label}
      </span>
      <div className="flex items-baseline gap-3 my-2">
        <span className="text-2xl font-extrabold text-slate-900 tracking-tight">
          {spec.value}
        </span>
        {spec.change && (
          <span
            className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-semibold ${
              spec.trend === 'up'
                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                : spec.trend === 'down'
                ? 'bg-rose-50 text-rose-700 border border-rose-200'
                : 'bg-slate-100 text-slate-700 border border-slate-200'
            }`}
          >
            {spec.trend === 'up' && <TrendingUp size={12} />}
            {spec.trend === 'down' && <TrendingDown size={12} />}
            {spec.trend === 'neutral' && <Minus size={12} />}
            {spec.change}
          </span>
        )}
      </div>
      {spec.subtext && (
        <span className="text-[11px] text-slate-500">{spec.subtext}</span>
      )}
    </div>
  )
}

export const TabsRenderer: React.FC<{ spec: TabsComponentSpec }> = ({
  spec,
}) => {
  const [activeTab, setActiveTab] = useState(0)

  if (!spec.items || spec.items.length === 0) return null

  return (
    <div
      data-testid="rendered-tabs"
      className="rounded-2xl bg-white border border-slate-200 overflow-hidden my-3 text-xs shadow-xs"
    >
      {spec.title && (
        <div className="px-4 pt-3 font-semibold text-slate-900 text-sm">
          {spec.title}
        </div>
      )}
      <div className="flex border-b border-slate-200 bg-slate-50 px-2 pt-2 gap-1 overflow-x-auto">
        {spec.items.map((tab, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => setActiveTab(idx)}
            className={`px-3 py-2 font-medium text-xs rounded-t-lg transition-all ${
              activeTab === idx
                ? 'bg-white text-emerald-700 border-t-2 border-emerald-600 font-semibold'
                : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="p-4 text-slate-700 leading-relaxed whitespace-pre-wrap">
        {spec.items[activeTab]?.content}
      </div>
    </div>
  )
}

export const AccordionRenderer: React.FC<{ spec: AccordionComponentSpec }> = ({
  spec,
}) => {
  const [openIndices, setOpenIndices] = useState<number[]>([0])

  const toggle = (idx: number) => {
    setOpenIndices((prev) =>
      prev.includes(idx) ? prev.filter((i) => i !== idx) : [...prev, idx]
    )
  }

  return (
    <div
      data-testid="rendered-accordion"
      className="rounded-2xl bg-white border border-slate-200 overflow-hidden my-3 text-xs divide-y divide-slate-200 shadow-xs"
    >
      {spec.title && (
        <div className="p-4 font-semibold text-slate-900 text-sm bg-slate-50">
          {spec.title}
        </div>
      )}
      {spec.items.map((item, idx) => {
        const isOpen = openIndices.includes(idx)
        return (
          <div key={idx}>
            <button
              type="button"
              onClick={() => toggle(idx)}
              className="w-full flex items-center justify-between p-3.5 text-left hover:bg-slate-50 transition-colors"
            >
              <span className="font-medium text-slate-800 text-xs">{item.title}</span>
              {isOpen ? <ChevronUp size={15} className="text-slate-500" /> : <ChevronDown size={15} className="text-slate-500" />}
            </button>
            {isOpen && (
              <div className="p-4 bg-slate-50/50 text-slate-600 leading-relaxed border-t border-slate-200">
                {item.content}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export const ComparisonRenderer: React.FC<{ spec: ComparisonComponentSpec }> = ({
  spec,
}) => {
  return (
    <div
      data-testid="rendered-comparison"
      className="rounded-2xl bg-white border border-slate-200 overflow-hidden my-3 text-xs shadow-xs"
    >
      <div className="p-4 border-b border-slate-200 font-semibold text-slate-900 text-sm">
        {spec.title}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="p-3 text-slate-500 font-medium">Feature</th>
              <th className="p-3 text-blue-700 font-semibold">{spec.item_a_name}</th>
              <th className="p-3 text-emerald-700 font-semibold">{spec.item_b_name}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {spec.features.map((feat, idx) => (
              <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                <td className="p-3 font-medium text-slate-800">{feat.name}</td>
                <td className="p-3 text-slate-600">{feat.item_a_val}</td>
                <td className="p-3 text-slate-600">{feat.item_b_val}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
