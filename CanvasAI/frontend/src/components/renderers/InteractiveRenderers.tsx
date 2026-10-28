import React, { useState, useEffect } from 'react'
import { Calculator, Play, CheckCircle } from 'lucide-react'
import type {
  CalculatorComponentSpec,
  InteractiveControlComponentSpec,
} from '../../types/uiPlan'
import { useMessageComponentContext } from '../../context/MessageComponentContext'

export const CalculatorRenderer: React.FC<{ spec: CalculatorComponentSpec }> = ({
  spec,
}) => {
  const [value, setValue] = useState(spec.initial_value || 1000)
  const [rate, setRate] = useState(spec.rate ?? 5.0)
  const [term, setTerm] = useState(spec.term ?? 3)

  const { setCalculatorState } = useMessageComponentContext()

  const calcType = spec.calculator_type || 'custom'
  const unit = spec.unit || '$'

  // Sync state to shared message context whenever inputs change
  useEffect(() => {
    setCalculatorState({
      initialValue: value,
      rate,
      term,
      calcType,
      updatedAt: Date.now(),
    })
  }, [value, rate, term, calcType, setCalculatorState])

  // Dynamic formula calculations based on calculator type
  const computedResult = (() => {
    if (calcType === 'loan') {
      const monthlyRate = (rate / 100) / 12
      const months = term * 12
      if (monthlyRate === 0) return (value / months).toFixed(2)
      const monthly =
        (value * (monthlyRate * Math.pow(1 + monthlyRate, months))) /
        (Math.pow(1 + monthlyRate, months) - 1)
      return isNaN(monthly) ? '0.00' : monthly.toFixed(2)
    }
    if (calcType === 'savings' || calcType === 'roi') {
      const futureVal = value * Math.pow(1 + rate / 100, term)
      return futureVal.toFixed(2)
    }
    if (calcType === 'percentage') {
      return ((value * rate) / 100).toFixed(2)
    }
    // Custom: scaled value
    return (value * (1 + rate / 100)).toFixed(2)
  })()

  return (
    <div
      data-testid="rendered-calculator"
      className="p-5 rounded-2xl bg-white border border-slate-200 text-xs shadow-xs my-3 space-y-4"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-emerald-50 text-emerald-600 border border-emerald-200/60">
            <Calculator size={16} />
          </div>
          <h4 className="font-semibold text-slate-900 text-sm">{spec.title}</h4>
        </div>
        <span className="text-[11px] font-mono uppercase px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
          {calcType}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Controls */}
        <div className="space-y-3">
          <div>
            <label className="block text-[11px] font-medium text-slate-500 mb-1">
              Base Principal Amount ({unit})
            </label>
            <input
              type="number"
              aria-label="Base Principal Amount"
              value={value}
              onChange={(e) => setValue(Number(e.target.value))}
              className="w-full px-3 py-1.5 rounded-lg bg-slate-50 border border-slate-200 text-slate-800 text-xs focus:outline-none focus:border-emerald-500 focus:bg-white transition-colors"
            />
          </div>

          <div>
            <div className="flex justify-between text-[11px] text-slate-500 mb-1">
              <span>Annual Rate:</span>
              <span className="font-mono text-slate-800 font-semibold">{rate}%</span>
            </div>
            <input
              type="range"
              aria-label="Annual Rate"
              min={0}
              max={30}
              step={0.5}
              value={rate}
              onChange={(e) => setRate(Number(e.target.value))}
              className="w-full accent-emerald-600 cursor-pointer"
            />
          </div>

          <div>
            <div className="flex justify-between text-[11px] text-slate-500 mb-1">
              <span>Duration / Term:</span>
              <span className="font-mono text-slate-800 font-semibold">{term} years</span>
            </div>
            <input
              type="range"
              aria-label="Duration / Term"
              min={1}
              max={30}
              step={1}
              value={term}
              onChange={(e) => setTerm(Number(e.target.value))}
              className="w-full accent-emerald-600 cursor-pointer"
            />
          </div>
        </div>

        {/* Live Calculation Output Display */}
        <div className="flex flex-col justify-center items-center p-4 rounded-xl bg-emerald-50/50 border border-emerald-200/80 text-center">
          <span className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
            {calcType === 'loan' ? 'Monthly Payment' : 'Estimated Value'}
          </span>
          <span className="text-2xl font-bold font-mono text-emerald-600">
            {unit}
            {Number(computedResult).toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </span>
          <span className="text-[11px] text-slate-500 mt-2">
            Dynamic result calculated client-side
          </span>
        </div>
      </div>
    </div>
  )
}

export const InteractiveControlRenderer: React.FC<{
  spec: InteractiveControlComponentSpec
}> = ({ spec }) => {
  const [sliderVal, setSliderVal] = useState<number>(
    spec.default_val ?? spec.min_val ?? 50
  )
  const [selectedOption, setSelectedOption] = useState<string>(
    spec.options?.[0] || ''
  )
  const [actionTriggered, setActionTriggered] = useState(false)

  const handleActionClick = () => {
    setActionTriggered(true)
    setTimeout(() => setActionTriggered(false), 2500)
  }

  return (
    <div
      data-testid="rendered-interactive-control"
      className="p-4 rounded-2xl bg-white border border-slate-200 text-xs shadow-xs my-3 space-y-3"
    >
      <div className="flex items-center justify-between">
        <h4 className="font-semibold text-slate-800 text-xs">{spec.title}</h4>
        <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
          {spec.control_type}
        </span>
      </div>

      {spec.control_type === 'slider' && (
        <div className="space-y-1.5">
          <div className="flex justify-between text-slate-500 text-[11px]">
            <span>{spec.label}</span>
            <span className="font-mono text-slate-800 font-semibold">{sliderVal}</span>
          </div>
          <input
            type="range"
            aria-label={spec.label}
            min={spec.min_val ?? 0}
            max={spec.max_val ?? 100}
            value={sliderVal}
            onChange={(e) => setSliderVal(Number(e.target.value))}
            className="w-full accent-emerald-600 cursor-pointer"
          />
        </div>
      )}

      {spec.control_type === 'dropdown' && spec.options && (
        <div className="space-y-1.5">
          <label className="block text-slate-500 text-[11px]">{spec.label}</label>
          <select
            aria-label={spec.label}
            value={selectedOption}
            onChange={(e) => setSelectedOption(e.target.value)}
            className="w-full px-3 py-1.5 rounded-lg bg-slate-50 border border-slate-200 text-slate-800 text-xs focus:outline-none focus:border-emerald-500 focus:bg-white"
          >
            {spec.options.map((opt, idx) => (
              <option key={idx} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </div>
      )}

      {spec.control_type === 'button' && (
        <div className="flex items-center justify-between pt-1">
          <span className="text-slate-600 text-xs">{spec.label}</span>
          <button
            type="button"
            onClick={handleActionClick}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold shadow-xs transition-colors"
          >
            {actionTriggered ? (
              <>
                <CheckCircle size={13} className="text-emerald-400" />
                <span>Action Executed</span>
              </>
            ) : (
              <>
                <Play size={12} className="fill-white" />
                <span>Trigger Action</span>
              </>
            )}
          </button>
        </div>
      )}

      {actionTriggered && (
        <div className="p-2 rounded bg-emerald-50 border border-emerald-200 text-emerald-800 text-[11px]">
          Verified safe action identifier executed: <code>{spec.action_id}</code>
        </div>
      )}
    </div>
  )
}
