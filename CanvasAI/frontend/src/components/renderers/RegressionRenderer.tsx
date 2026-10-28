import React, { useState, useMemo } from 'react'
import {
  ResponsiveContainer,
  ComposedChart,
  Scatter,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'
import { Sparkles, RotateCcw, LineChart as ChartIcon } from 'lucide-react'
import type { RegressionComponentSpec } from '../../types/uiPlan'

export const RegressionRenderer: React.FC<{ spec: RegressionComponentSpec }> = ({
  spec,
}) => {
  const points = spec.points || []

  // Calculate Ordinary Least Squares (OLS) parameters deterministically
  const ols = useMemo(() => {
    const n = points.length
    if (n < 2) return { slope: 1, intercept: 0, meanY: 0, ssTot: 1 }

    const sumX = points.reduce((acc, p) => acc + p.x, 0)
    const sumY = points.reduce((acc, p) => acc + p.y, 0)
    const meanX = sumX / n
    const meanY = sumY / n

    let num = 0
    let den = 0
    let ssTot = 0

    for (const p of points) {
      num += (p.x - meanX) * (p.y - meanY)
      den += (p.x - meanX) ** 2
      ssTot += (p.y - meanY) ** 2
    }

    const slope = den !== 0 ? num / den : 0
    const intercept = meanY - slope * meanX
    return {
      slope: Number(slope.toFixed(3)),
      intercept: Number(intercept.toFixed(3)),
      meanY,
      ssTot: ssTot || 1,
    }
  }, [points])

  // Initial slope and intercept (prefer spec.initial_* or OLS)
  const defaultW = spec.initial_slope ?? ols.slope
  const defaultB = spec.initial_intercept ?? ols.intercept

  // Controlled React state for parameters
  const [w, setW] = useState<number>(defaultW)
  const [b, setB] = useState<number>(defaultB)
  const [showResiduals, setShowResiduals] = useState<boolean>(spec.show_residuals ?? true)

  // Compute domain bounds for numerical X & Y axes
  const { minX, maxX, minY, maxY } = useMemo(() => {
    if (points.length === 0) return { minX: 0, maxX: 10, minY: 0, maxY: 10 }
    let mX = points[0].x, mxX = points[0].x
    let mY = points[0].y, mxY = points[0].y
    for (const p of points) {
      if (p.x < mX) mX = p.x
      if (p.x > mxX) mxX = p.x
      if (p.y < mY) mY = p.y
      if (p.y > mxY) mxY = p.y
    }
    const padX = Math.max((mxX - mX) * 0.15, 1)
    const padY = Math.max((mxY - mY) * 0.15, 1)
    return {
      minX: Number((mX - padX).toFixed(1)),
      maxX: Number((mxX + padX).toFixed(1)),
      minY: Number((mY - padY).toFixed(1)),
      maxY: Number((mxY + padY).toFixed(1)),
    }
  }, [points])

  // Live statistical metrics: Predictions, Residuals, MSE, and R^2
  const stats = useMemo(() => {
    if (points.length === 0) return { mse: 0, r2: 0, residuals: [] }
    let ssRes = 0
    const residuals = points.map((p) => {
      const yHat = w * p.x + b
      const res = p.y - yHat
      ssRes += res * res
      return { x: p.x, yObs: p.y, yHat, residual: res }
    })
    const mse = ssRes / points.length
    const r2 = Math.max(0, 1 - ssRes / ols.ssTot)
    return {
      mse: Number(mse.toFixed(3)),
      r2: Number(r2.toFixed(3)),
      residuals,
    }
  }, [points, w, b, ols.ssTot])

  // Fitted line data points across the numeric X domain
  const lineData = useMemo(() => {
    return [
      { x: minX, yHat: Number((w * minX + b).toFixed(3)) },
      { x: maxX, yHat: Number((w * maxX + b).toFixed(3)) },
    ]
  }, [minX, maxX, w, b])

  // Merged dataset for ComposedChart
  const combinedChartData = useMemo(() => {
    // Generate sample steps along X to plot a smooth line alongside observed scatter points
    const stepCount = 20
    const stepSize = (maxX - minX) / (stepCount - 1)
    const data: Array<{ x: number; y?: number; yHat?: number }> = []

    // Add line points
    for (let i = 0; i < stepCount; i++) {
      const xVal = Number((minX + i * stepSize).toFixed(3))
      data.push({ x: xVal, yHat: Number((w * xVal + b).toFixed(3)) })
    }

    // Add observed scatter points
    for (const p of points) {
      data.push({ x: p.x, y: p.y, yHat: Number((w * p.x + b).toFixed(3)) })
    }

    data.sort((a, b) => a.x - b.x)
    return data
  }, [points, minX, maxX, w, b])

  const handleFitLeastSquares = () => {
    setW(ols.slope)
    setB(ols.intercept)
  }

  const handleReset = () => {
    setW(defaultW)
    setB(defaultB)
  }

  return (
    <div
      data-testid="rendered-regression"
      className="p-5 rounded-2xl bg-white border border-slate-200 text-xs shadow-xs my-4 space-y-4"
    >
      {/* Header and Title */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-purple-50 text-purple-600 border border-purple-200/60">
            <ChartIcon size={16} />
          </div>
          <div>
            <h4 className="font-semibold text-slate-900 text-sm">{spec.title}</h4>
            <span className="text-[11px] text-slate-500">
              Interactive Linear Model: <code className="text-purple-700 bg-purple-50 px-1 py-0.5 rounded font-mono">ŷ = w·x + b</code>
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {spec.allow_fit !== false && (
            <button
              type="button"
              data-testid="fit-least-squares-btn"
              onClick={handleFitLeastSquares}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-purple-50 hover:bg-purple-100 text-purple-700 border border-purple-200 text-xs font-medium transition-colors shadow-xs"
              title="Calculate Ordinary Least Squares (OLS) line"
            >
              <Sparkles size={12} className="text-purple-600" />
              Fit to Data (OLS)
            </button>
          )}
          <button
            type="button"
            data-testid="reset-regression-btn"
            onClick={handleReset}
            className="p-1 rounded text-slate-400 hover:text-slate-600"
            title="Reset to initial parameters"
          >
            <RotateCcw size={13} />
          </button>
        </div>
      </div>

      {spec.description && (
        <p className="text-xs text-slate-600 leading-relaxed bg-slate-50 p-2.5 rounded-lg border border-slate-200">
          {spec.description}
        </p>
      )}

      {/* Main Coordinate Graph (Scatter points + Fitted Regression Line) */}
      <div className="w-full h-72 min-h-[288px] relative bg-slate-50/70 rounded-xl p-2 border border-slate-200">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={combinedChartData} margin={{ top: 15, right: 20, bottom: 20, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              type="number"
              dataKey="x"
              domain={[minX, maxX]}
              stroke="#64748b"
              fontSize={11}
              label={{ value: spec.x_label || 'X', position: 'insideBottom', offset: -10, fill: '#64748b', fontSize: 11 }}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[minY, maxY]}
              stroke="#64748b"
              fontSize={11}
              label={{ value: spec.y_label || 'Y', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 11 }}
            />
            <Tooltip
              content={({ payload }) => {
                if (!payload || payload.length === 0) return null
                const item = payload[0].payload
                return (
                  <div className="bg-white border border-slate-200 p-2 rounded text-xs text-slate-800 font-mono shadow-md">
                    <div>x: {item.x}</div>
                    {item.y !== undefined && <div className="text-sky-600 font-medium">y (Observed): {item.y}</div>}
                    {item.yHat !== undefined && <div className="text-purple-600 font-medium">ŷ (Predicted): {item.yHat}</div>}
                  </div>
                )
              }}
            />
            <Legend wrapperStyle={{ fontSize: '11px', color: '#64748b', paddingTop: '8px' }} />
            {/* Scatter points for observed data */}
            <Scatter
              name="Observed Points"
              data={points}
              fill="#0284c7"
              line={false}
              shape="circle"
              legendType="circle"
            />
            {/* Fitted Model Line */}
            <Line
              type="linear"
              name={`Model Line: ŷ = ${w}x ${b >= 0 ? `+ ${b}` : `- ${Math.abs(b)}`}`}
              dataKey="yHat"
              data={lineData}
              stroke="#8b5cf6"
              strokeWidth={3}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>

        {/* Semantic DOM markers for automated test verification and accessibility */}
        <div data-testid="regression-scatter-points" className="hidden">
          {points.map((p, i) => (
            <span key={i} data-point-x={p.x} data-point-y={p.y}>
              Point:({p.x},{p.y})
            </span>
          ))}
        </div>
        <div
          data-testid="regression-line-params"
          data-slope={w}
          data-intercept={b}
          data-mse={stats.mse}
          data-r2={stats.r2}
          className="hidden"
        >
          Line: w={w}, b={b}
        </div>
      </div>

      {/* Real-Time Parameter Sliders & Formula Readout */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
        {/* Sliders */}
        <div className="space-y-3 p-3.5 rounded-xl bg-slate-50 border border-slate-200">
          <div>
            <div className="flex justify-between text-[11px] text-slate-600 mb-1">
              <span className="font-semibold">Slope (w):</span>
              <span className="font-mono text-purple-700 font-bold">{w}</span>
            </div>
            <input
              type="range"
              aria-label="Slope w"
              data-testid="slope-slider"
              min={Number((ols.slope - 10).toFixed(1))}
              max={Number((ols.slope + 10).toFixed(1))}
              step={0.05}
              value={w}
              onChange={(e) => setW(Number(e.target.value))}
              className="w-full accent-purple-600 cursor-pointer"
            />
          </div>

          <div>
            <div className="flex justify-between text-[11px] text-slate-600 mb-1">
              <span className="font-semibold">Intercept (b):</span>
              <span className="font-mono text-purple-700 font-bold">{b}</span>
            </div>
            <input
              type="range"
              aria-label="Intercept b"
              data-testid="intercept-slider"
              min={Number((ols.intercept - 20).toFixed(1))}
              max={Number((ols.intercept + 20).toFixed(1))}
              step={0.1}
              value={b}
              onChange={(e) => setB(Number(e.target.value))}
              className="w-full accent-purple-600 cursor-pointer"
            />
          </div>

          <div className="flex items-center justify-between pt-1">
            <label className="flex items-center gap-2 cursor-pointer select-none text-[11px] text-slate-600">
              <input
                type="checkbox"
                data-testid="residuals-checkbox"
                checked={showResiduals}
                onChange={(e) => setShowResiduals(e.target.checked)}
                className="rounded accent-purple-600"
              />
              Show Residual Details
            </label>
            <span className="text-[10px] text-slate-400">Updates locally without LLM latency</span>
          </div>
        </div>

        {/* Model Performance & Stats Card */}
        <div className="flex flex-col justify-between p-3.5 rounded-xl bg-slate-50 border border-slate-200 space-y-2">
          <div>
            <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider block mb-1">
              Fitted Model Formula
            </span>
            <div
              data-testid="regression-equation"
              className="text-base font-bold font-mono text-slate-900 bg-white px-3 py-1.5 rounded-lg border border-slate-200 text-center shadow-xs"
            >
              ŷ = {w}·x {b >= 0 ? `+ ${b}` : `- ${Math.abs(b)}`}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 pt-1">
            <div className="p-2 rounded-lg bg-white border border-slate-200 text-center shadow-xs">
              <span className="text-[10px] text-slate-500 uppercase tracking-wider block">MSE (Error)</span>
              <span data-testid="regression-mse" className="text-sm font-bold font-mono text-amber-600">
                {stats.mse}
              </span>
            </div>
            <div className="p-2 rounded-lg bg-white border border-slate-200 text-center shadow-xs">
              <span className="text-[10px] text-slate-500 uppercase tracking-wider block">R² Score</span>
              <span data-testid="regression-r2" className="text-sm font-bold font-mono text-emerald-600">
                {stats.r2}
              </span>
            </div>
          </div>

          {showResiduals && (
            <div className="text-[10px] text-slate-500 italic text-center pt-1">
              Sum of squared residuals: {(stats.mse * points.length).toFixed(2)} across {points.length} samples
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
