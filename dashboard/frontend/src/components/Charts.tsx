import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { EppScoreRecord } from '../types'
import { useTheme, type Theme } from '../theme'
import { fmtNum } from '../format'

const MS_TOOLTIP = (value: any) =>
  value == null ? '—' : `${Number(value).toFixed(0)} ms`

// Recharts renders SVG attributes, so CSS variables cannot be used; colors
// are chosen per theme instead.
export function chartColors(theme: Theme) {
  return theme === 'dark'
    ? {
        grid: '#2c333b',
        axis: '#4a545e',
        text: '#98a2ac',
        tooltip: { background: '#171c21', border: '1px solid #2c333b', borderRadius: 4, color: '#e4e8ec' } as const,
        tooltipLabel: { color: '#98a2ac' } as const,
      }
    : {
        grid: '#e5e9ee',
        axis: '#c3cbd3',
        text: '#5c6670',
        tooltip: { background: '#ffffff', border: '1px solid #d9dee3', borderRadius: 4, color: '#1b1f23' } as const,
        tooltipLabel: { color: '#5c6670' } as const,
      }
}

export function MetricBarChart({
  data,
  height = 300,
}: {
  data: { label: string; p50: number | null; p99: number | null }[]
  height?: number
}) {
  const { theme } = useTheme()
  const colors = chartColors(theme)
  if (!data.length) return <div className="muted">No data.</div>
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 48 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} />
        <XAxis
          dataKey="label"
          angle={-30}
          textAnchor="end"
          height={70}
          interval={0}
          stroke={colors.axis}
          tick={{ fontSize: 11, fill: colors.text }}
        />
        <YAxis stroke={colors.axis} tick={{ fontSize: 11, fill: colors.text }} />
        <Tooltip formatter={MS_TOOLTIP} contentStyle={colors.tooltip} labelStyle={colors.tooltipLabel} />
        <Legend />
        <Bar dataKey="p50" name="p50" fill="#3d7dc8" />
        <Bar dataKey="p99" name="p99" fill="#c25b4e" />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function Histogram({
  values,
  buckets = 24,
  height = 260,
}: {
  values: number[]
  buckets?: number
  height?: number
}) {
  const { theme } = useTheme()
  const colors = chartColors(theme)
  const data = useMemo(() => {
    const clean = values.filter((v) => v != null && Number.isFinite(v))
    if (!clean.length) return []
    const min = Math.min(...clean)
    const max = Math.max(...clean)
    const width = (max - min) / buckets || 1
    const counts = new Array(buckets).fill(0)
    for (const value of clean) {
      const index = Math.min(buckets - 1, Math.floor((value - min) / width))
      counts[index] += 1
    }
    return counts.map((count, index) => ({
      range: `${Math.round(min + index * width)}+`,
      count,
    }))
  }, [values, buckets])

  if (!data.length) return <div className="muted">No samples.</div>
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 24 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} />
        <XAxis dataKey="range" stroke={colors.axis} tick={{ fontSize: 11, fill: colors.text }} />
        <YAxis stroke={colors.axis} tick={{ fontSize: 11, fill: colors.text }} allowDecimals={false} />
        <Tooltip contentStyle={colors.tooltip} labelStyle={colors.tooltipLabel} />
        <Bar dataKey="count" name="requests" fill="#5a8a5c" />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function EppScoreView({ record }: { record: EppScoreRecord }) {
  if (!record.decisions?.length) {
    return (
      <div className="muted">
        No EPP score records for this request (status: {record.status}).
      </div>
    )
  }
  return (
    <div>
      {record.decisions.map((decision, index) => {
        const scorerNames = Array.from(
          new Set(decision.endpoints.flatMap((e) => Object.keys(e.scores))),
        ).sort()
        return (
          <div key={index} style={{ marginBottom: 8 }}>
            {record.decisions.length > 1 && (
              <div className="muted">
                Decision {index + 1} ({decision.epp_pod})
              </div>
            )}
            <table className="data">
              <thead>
                <tr>
                  <th>Endpoint</th>
                  {scorerNames.map((name) => (
                    <th key={name} className="num" title={name}>
                      {name}
                    </th>
                  ))}
                  <th className="num">Total</th>
                  <th>Picked</th>
                </tr>
              </thead>
              <tbody>
                {decision.endpoints.map((endpoint) => (
                  <tr key={endpoint.endpoint_id}>
                    <td className="mono">{endpoint.pod || endpoint.endpoint_id}</td>
                    {scorerNames.map((name) => (
                      <td key={name} className="num">
                        {fmtNum(endpoint.scores[name]?.raw, 3)} /{' '}
                        {fmtNum(endpoint.scores[name]?.weighted, 3)}
                      </td>
                    ))}
                    <td className="num">{fmtNum(endpoint.weighted_total, 3)}</td>
                    <td>
                      {endpoint.selected == null ? '—' : endpoint.selected ? 'yes' : 'no'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {decision.issues?.length ? (
              <div className="warn-text">Issues: {decision.issues.join('; ')}</div>
            ) : null}
          </div>
        )
      })}
      <div className="muted" style={{ fontSize: 12 }}>
        Cells show raw / weighted score per scorer.
      </div>
    </div>
  )
}
