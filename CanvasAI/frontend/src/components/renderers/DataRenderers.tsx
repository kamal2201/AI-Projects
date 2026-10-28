import React, { useState, useMemo } from 'react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from 'recharts'
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import type { ChartComponentSpec, TableComponentSpec } from '../../types/uiPlan'
import { RegressionRenderer } from './RegressionRenderer'
import { useMessageComponentContext } from '../../context/MessageComponentContext'

const CHART_COLORS = ['#10b981', '#3b82f6', '#8b5cf6', '#f59e0b', '#ec4899', '#06b6d4']

export const ChartRenderer: React.FC<{ spec: ChartComponentSpec }> = ({
  spec,
}) => {
  const chartType = spec.chart_type || 'bar'
  const { calculatorState } = useMessageComponentContext()

  // Route regression and scatter plots to RegressionRenderer instead of bar charts
  if (
    chartType === 'scatter' ||
    (chartType as string) === 'regression' ||
    spec.title.toLowerCase().includes('regression')
  ) {
    const pts = spec.labels.map((l, i) => {
      const numX = Number(l)
      const numY = spec.values[i] ?? 0
      return { x: isNaN(numX) ? i + 1 : numX, y: numY }
    })
    return (
      <RegressionRenderer
        spec={{
          type: 'regression',
          title: spec.title,
          points: pts,
          x_label: 'X (Feature)',
          y_label: 'Y (Target)',
        }}
      />
    )
  }

  // Calculate dynamic values if linked to an active calculator
  const dynamicValues = useMemo(() => {
    if (!calculatorState) {
      return spec.values
    }

    const { initialValue, rate, term, calcType } = calculatorState
    const n = spec.labels.length
    if (n === 0) return spec.values

    return spec.labels.map((_, idx) => {
      const progress = n > 1 ? idx / (n - 1) : 1
      if (calcType === 'savings' || calcType === 'roi') {
        const baseVal = spec.values[idx] ?? initialValue
        const baseFirst = spec.values[0] || initialValue || 1
        const ratio = initialValue / (baseFirst || 1)
        // Scaled compound growth based on live principal and rate adjustments
        const growthMult = Math.pow(1 + (rate - 5) / 100, (term || 3) * progress)
        return Math.round(baseVal * ratio * growthMult)
      } else if (calcType === 'loan') {
        const monthlyRate = (rate / 100) / 12
        const totalMonths = (term || 1) * 12
        const currentMonth = Math.round(progress * totalMonths)
        if (monthlyRate === 0) {
          return Math.round(Math.max(0, initialValue - (initialValue / totalMonths) * currentMonth))
        }
        const monthlyPayment =
          (initialValue * (monthlyRate * Math.pow(1 + monthlyRate, totalMonths))) /
          (Math.pow(1 + monthlyRate, totalMonths) - 1)
        const remaining =
          initialValue * Math.pow(1 + monthlyRate, currentMonth) -
          (monthlyPayment * (Math.pow(1 + monthlyRate, currentMonth) - 1)) / monthlyRate
        return Math.round(Math.max(0, remaining))
      } else {
        return Math.round(initialValue * (1 + (rate / 100) * progress))
      }
    })
  }, [spec.labels, spec.values, calculatorState])

  // Format data for recharts
  const chartData = useMemo(() => {
    return spec.labels.map((label, idx) => {
      const item: Record<string, string | number> = {
        name: label,
        value: dynamicValues[idx] ?? spec.values[idx] ?? 0,
      }
      if (spec.series) {
        for (const s of spec.series) {
          item[s.name] = s.values[idx] ?? 0
        }
      }
      return item
    })
  }, [spec.labels, spec.values, spec.series, dynamicValues])

  return (
    <div
      data-testid="rendered-chart"
      className="p-5 rounded-2xl bg-white border border-slate-200 text-xs shadow-xs my-3"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <h4 className="font-semibold text-slate-800 text-sm">{spec.title}</h4>
          {calculatorState && (
            <span className="text-[11px] font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200 flex items-center gap-1.5 shadow-xs">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Linked to Calculator
            </span>
          )}
        </div>
        <span className="text-[11px] font-mono uppercase px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
          {chartType}
        </span>
      </div>

      <div className="w-full h-64 min-h-[256px]">
        <ResponsiveContainer width="100%" height="100%" minWidth={100} minHeight={200}>
          {chartType === 'line' ? (
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#ffffff',
                  borderColor: '#e2e8f0',
                  borderRadius: '8px',
                  color: '#0f172a',
                  boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.08)',
                }}
              />
              <Legend wrapperStyle={{ fontSize: '11px', color: '#64748b' }} />
              <Line
                type="monotone"
                dataKey="value"
                name="Value"
                stroke="#10b981"
                strokeWidth={2}
                dot={{ r: 4, fill: '#10b981' }}
              />
            </LineChart>
          ) : chartType === 'area' ? (
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#ffffff',
                  borderColor: '#e2e8f0',
                  borderRadius: '8px',
                  color: '#0f172a',
                  boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.08)',
                }}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke="#059669"
                fill="#10b981"
                fillOpacity={0.2}
              />
            </AreaChart>
          ) : chartType === 'pie' ? (
            <PieChart>
              <Tooltip
                contentStyle={{
                  backgroundColor: '#ffffff',
                  borderColor: '#e2e8f0',
                  borderRadius: '8px',
                  color: '#0f172a',
                  boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.08)',
                }}
              />
              <Legend wrapperStyle={{ fontSize: '11px', color: '#64748b' }} />
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={80}
                label
              >
                {chartData.map((_, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={CHART_COLORS[index % CHART_COLORS.length]}
                  />
                ))}
              </Pie>
            </PieChart>
          ) : (
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#ffffff',
                  borderColor: '#e2e8f0',
                  borderRadius: '8px',
                  color: '#0f172a',
                  boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.08)',
                }}
              />
              <Legend wrapperStyle={{ fontSize: '11px', color: '#64748b' }} />
              <Bar
                dataKey="value"
                name="Value"
                fill="#10b981"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export const TableRenderer: React.FC<{ spec: TableComponentSpec }> = ({
  spec,
}) => {
  // Do not render empty or placeholder tables
  if (
    !spec.rows ||
    spec.rows.length === 0 ||
    (spec.rows.length === 1 &&
      (spec.rows[0]?.[1] === 'No structured records provided' ||
        spec.rows[0]?.[0] === 'Data'))
  ) {
    return null
  }

  const [sortCol, setSortCol] = useState<number | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const handleSort = (colIndex: number) => {
    if (sortCol === colIndex) {
      if (sortDir === 'asc') setSortDir('desc')
      else setSortCol(null)
    } else {
      setSortCol(colIndex)
      setSortDir('asc')
    }
  }

  const sortedRows = useMemo(() => {
    if (sortCol === null) return spec.rows
    const rows = [...spec.rows]
    rows.sort((a, b) => {
      const valA = a[sortCol] ?? ''
      const valB = b[sortCol] ?? ''
      const numA = Number(valA.replace(/[^0-9.-]+/g, ''))
      const numB = Number(valB.replace(/[^0-9.-]+/g, ''))
      if (!isNaN(numA) && !isNaN(numB)) {
        return sortDir === 'asc' ? numA - numB : numB - numA
      }
      return sortDir === 'asc'
        ? valA.localeCompare(valB)
        : valB.localeCompare(valA)
    })
    return rows
  }, [spec.rows, sortCol, sortDir])

  return (
    <div
      data-testid="rendered-table"
      className="rounded-2xl bg-white border border-slate-200 overflow-hidden my-3 text-xs shadow-xs"
    >
      <div className="p-4 border-b border-slate-200 font-semibold text-slate-800 text-sm bg-white">
        {spec.title}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              {spec.headers.map((header, idx) => (
                <th
                  key={idx}
                  onClick={() => handleSort(idx)}
                  className="p-3 text-slate-600 font-medium cursor-pointer hover:bg-slate-100 select-none transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>{header}</span>
                    {sortCol === idx ? (
                      sortDir === 'asc' ? (
                        <ArrowUp size={12} className="text-emerald-600" />
                      ) : (
                        <ArrowDown size={12} className="text-emerald-600" />
                      )
                    ) : (
                      <ArrowUpDown size={12} className="text-slate-400" />
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {sortedRows.map((row, rIdx) => (
              <tr key={rIdx} className="hover:bg-slate-50/80 transition-colors">
                {row.map((cell, cIdx) => (
                  <td key={cIdx} className="p-3 text-slate-700">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
