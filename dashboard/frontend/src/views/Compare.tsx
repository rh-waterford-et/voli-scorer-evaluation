import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
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
import { MetricBarChart, chartColors } from '../components/Charts'
import HelpHint from '../components/HelpHint'
import { api } from '../api'
import { useTheme } from '../theme'
import type { ProfileCheck, ProfilesCheckResponse, RunDetail, ScriptRun } from '../types'
import { METRIC_LABELS, METRIC_ORDER, fmtMs, loadLabel } from '../format'

type Stat = 'mean' | 'p50' | 'p99'

function shortLabel(detail: RunDetail, index: number): string {
  const base = (detail.name || detail.id).replace(/\s+/g, ' ').slice(0, 18)
  return `${index + 1}: ${base}`
}

export default function Compare() {
  const [searchParams] = useSearchParams()
  const ids = (searchParams.get('ids') ?? '').split(',').filter(Boolean)
  const [details, setDetails] = useState<RunDetail[]>([])
  const [error, setError] = useState<string | null>(null)
  const [metric, setMetric] = useState('e2e_ms')
  const [stat, setStat] = useState<Stat>('p50')
  const [load, setLoad] = useState('')
  const [scorerCheck, setScorerCheck] = useState<ProfilesCheckResponse | null>(null)

  useEffect(() => {
    if (!ids.length) return
    Promise.all(ids.map((id) => api.run(id)))
      .then((result) => setDetails(result.filter((d) => d.results?.runs?.length)))
      .catch((cause) => setError(String(cause)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  // Scorer operability for the compared profiles (first run's endpoint; a
  // real endpoint mismatch is flagged separately by the confounder check).
  useEffect(() => {
    if (!details.length) return
    const first = details[0]
    const endpoint =
      first.params?.endpoint ??
      (first.results?.endpoint?.includes('/v1/audio/speech')
        ? '/v1/audio/speech'
        : '/v1/chat/completions')
    api
      .profileCheck(endpoint, {
        namespace: first.params?.namespace ?? 'vllm-omni-validation',
        epp_deployment: first.params?.epp_deployment ?? 'endpoint-picker-epp',
        epp_container: first.params?.epp_container ?? 'epp',
      })
      .then(setScorerCheck)
      .catch(() => setScorerCheck(null))
  }, [details])

  const allRuns = useMemo(() => details.flatMap((detail) => detail.results?.runs ?? []), [details])
  const metricKeys = useMemo(
    () => METRIC_ORDER.filter((key) => allRuns.some((run) => (run.metrics?.[key]?.n ?? 0) > 0)),
    [allRuns],
  )
  const loads = useMemo(
    () => Array.from(new Set(allRuns.map((run) => loadLabel(run)))).sort(),
    [allRuns],
  )
  const profiles = useMemo(
    () => Array.from(new Set(allRuns.map((run) => run.profile))).sort(),
    [allRuns],
  )

  useEffect(() => {
    if (!metricKeys.includes(metric) && metricKeys.length) {
      setMetric(metricKeys.includes('e2e_ms') ? 'e2e_ms' : metricKeys[metricKeys.length - 1])
    }
    if (!loads.includes(load) && loads.length) setLoad(loads[0])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metricKeys, loads])

  const findRun = (detail: RunDetail, profile: string): ScriptRun | undefined =>
    detail.results?.runs.find((run) => run.profile === profile && loadLabel(run) === load)

  const cellValue = (detail: RunDetail, profile: string): number | null => {
    const run = findRun(detail, profile)
    return run ? run.metrics?.[metric]?.[stat] ?? null : null
  }

  // Confounders that can dominate latency differences between runs. Repository
  // reports carry no params, so their prompt/session settings count as unknown
  // and only confirmed differences (two or more distinct known values) warn.
  const promptOf = (detail: RunDetail): string | null => {
    if (!detail.params) return null
    const text = (detail.params.prompts_text ?? '').trim()
    if (text) return text
    return (detail.params.prompt ?? '').trim() || '(script default)'
  }
  const promptPreview = (value: string) => {
    const flat = value.replace(/\s+/g, ' ').trim()
    return flat.length > 64 ? `${flat.slice(0, 61)}…` : flat
  }
  const sessionOf = (detail: RunDetail): number | null =>
    detail.params ? detail.params.session_length ?? 0 : null
  const modalitiesOf = (detail: RunDetail): string =>
    (detail.results?.modalities ?? []).join(',') || detail.params?.modalities || '—'

  const models = Array.from(new Set(details.map((d) => d.results?.model ?? d.params?.model ?? '—')))
  const endpoints = Array.from(
    new Set(details.map((d) => d.results?.endpoint ?? d.params?.endpoint ?? '—')),
  )
  const prompts = Array.from(
    new Set(details.map(promptOf).filter((value): value is string => value != null)),
  )
  const sessions = Array.from(
    new Set(details.map(sessionOf).filter((value): value is number => value != null)),
  )
  const modalities = Array.from(new Set(details.map(modalitiesOf)))

  const mismatched: string[] = []
  if (models.length > 1) mismatched.push('models')
  if (endpoints.length > 1) mismatched.push('endpoints')
  if (prompts.length > 1) mismatched.push('prompts')
  if (modalities.length > 1) mismatched.push('output modalities')
  if (sessions.length > 1) mismatched.push(`session settings (lengths ${sessions.join(' vs ')})`)

  // Profiles whose scorers have no usable signal (unsupported / not-useful /
  // missing prerequisites) make rankings misleading: a "deaf" scorer can win.
  const inoperableProfiles = new Set<string>()
  // Limited (partial signal) or unverified scorers keep their rankings but
  // get an interpretation note.
  const caveatedProfiles = new Map<string, ProfileCheck>()
  if (scorerCheck) {
    for (const detail of details) {
      for (const run of detail.results?.runs ?? []) {
        const check = scorerCheck.profiles[run.profile]
        if (!check || check.severity === 'ok') continue
        if (check.severity === 'bad') inoperableProfiles.add(run.profile)
        else caveatedProfiles.set(run.profile, check)
      }
    }
  }
  if (inoperableProfiles.size) {
    mismatched.push(`scorer operability (${Array.from(inoperableProfiles).join(', ')})`)
  }
  const operabilityBlocked = inoperableProfiles.size > 0
  const settingsMismatched = mismatched.length > (operabilityBlocked ? 1 : 0)
  const comparable = mismatched.length === 0

  // Latency-like metrics: lower is better. Winner highlighting is suppressed
  // while the runs differ in a confounder (prompt, session, model, ...).
  const isLowerBetter = !metric.startsWith('unknown')
  const bestByProfile = new Map<string, number>()
  if (isLowerBetter && comparable) {
    for (const profile of profiles) {
      const values = details
        .map((detail) => cellValue(detail, profile))
        .filter((value): value is number => value != null)
      if (values.length) bestByProfile.set(profile, Math.min(...values))
    }
  }

  const chartData = profiles.map((profile) => {
    const row: Record<string, string | number | null> = { profile }
    details.forEach((detail, index) => {
      row[shortLabel(detail, index)] = cellValue(detail, profile)
    })
    return row
  })
  const chartBars = details.map((detail, index) => ({
    key: shortLabel(detail, index),
    color: ['#3d7dc8', '#c25b4e', '#5a8a5c', '#8a6bb5', '#b58a3d'][index % 5],
  }))

  if (!ids.length) {
    return (
      <div>
        <h1>Compare runs</h1>
        <div className="panel muted">
          Select runs in the History view, then click "Compare selected".
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <h1>Compare runs</h1>
        <div className="error-text panel">{error}</div>
      </div>
    )
  }

  if (!details.length) {
    return (
      <div>
        <h1>Compare runs</h1>
        <div className="panel muted">Loading…</div>
      </div>
    )
  }

  return (
    <div>
      <div className="page-head">
        <h1>Compare runs</h1>
      </div>

      {!comparable && (
        <div className="warn-text panel">
          <strong>Not directly comparable:</strong> the selected runs differ in{' '}
          {mismatched.join(', ')} — winner highlighting is disabled.
          {settingsMismatched && (
            <>
              {' '}Latency depends heavily on input length, output modalities, and session
              behavior, so differences may reflect those settings rather than the routing
              profiles.
            </>
          )}
          {operabilityBlocked && (
            <>
              {' '}A scorer with no usable signal for this workload can still appear to win,
              so its rankings would be misleading.
            </>
          )}
          {prompts.length > 1 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>
              {prompts.map((prompt) => {
                const labels = details
                  .map((detail, index) => (promptOf(detail) === prompt ? shortLabel(detail, index) : null))
                  .filter((value): value is string => value != null)
                  .join(', ')
                return (
                  <li key={prompt} className="muted">
                    {labels}: “{promptPreview(prompt)}”
                  </li>
                )
              })}
            </ul>
          )}
          {inoperableProfiles.size > 0 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>
              {Array.from(inoperableProfiles).map((profile) => (
                <li key={profile} className="muted">
                  <span className="mono">{profile}</span>:{' '}
                  {scorerCheck?.profiles[profile]?.reasons.join(' ')}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {caveatedProfiles.size > 0 && (
        <div className="panel warn-text">
          <strong>Interpretation caveats</strong>
          {comparable
            ? " — rankings stay enabled, but these profiles' scorers operate with a partial or unverified signal for this workload:"
            : " — these profiles' scorers also operate with a partial or unverified signal (less severe than the blocking issues above):"}
          <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>
            {Array.from(caveatedProfiles.entries()).map(([profile, check]) => (
              <li key={profile} className="muted">
                <span className="mono">{profile}</span>: {check.reasons.join(' ')}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="panel">
        <div className="actions">
          <label>
            Metric
            <HelpHint text="Which latency metric to compare across the selected runs." />
            <select value={metric} onChange={(e) => setMetric(e.target.value)}>
              {metricKeys.map((key) => (
                <option key={key} value={key}>{METRIC_LABELS[key] ?? key}</option>
              ))}
            </select>
          </label>
          <label>
            Statistic
            <HelpHint text="Which summary statistic to compare: mean (average), p50 (median), or p99 (tail)." />
            <select value={stat} onChange={(e) => setStat(e.target.value as Stat)}>
              <option value="mean">mean</option>
              <option value="p50">p50</option>
              <option value="p99">p99</option>
            </select>
          </label>
          <label>
            Load
            <HelpHint text="Only profile runs at this load setting (requests × concurrency) are compared." />
            <select value={load} onChange={(e) => setLoad(e.target.value)}>
              {loads.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Profile</th>
                {details.map((detail, index) => (
                  <th key={detail.id} className="num" title={detail.id}>
                    {shortLabel(detail, index)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {profiles.map((profile) => {
                const best = bestByProfile.get(profile)
                return (
                  <tr key={profile}>
                    <td className="mono">{profile}</td>
                    {details.map((detail) => {
                      const value = cellValue(detail, profile)
                      const isBest = value != null && best != null && Math.abs(value - best) < 1e-9
                      return (
                        <td key={detail.id} className={`num${isBest ? ' best' : ''}`}>
                          {fmtMs(value)}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="muted">
          {comparable ? (
            <>
              Highlighted cells are the best (lowest) value for that profile at load {load || '—'}.
            </>
          ) : (
            <>
              Winner highlighting is disabled because the runs differ in {mismatched.join(', ')}.
            </>
          )}{' '}
          Missing cells mean the run has no matching profile/load combination.
        </p>
      </div>

      <div className="panel">
        <h2>
          {METRIC_LABELS[metric] ?? metric} · {stat} · load {load || '—'}
        </h2>
        <MetricBarChartWrapper chartData={chartData} chartBars={chartBars} metric={metric} stat={stat} />
      </div>
    </div>
  )
}

function MetricBarChartWrapper({
  chartData,
  chartBars,
  metric,
  stat,
}: {
  chartData: Record<string, string | number | null>[]
  chartBars: { key: string; color: string }[]
  metric: string
  stat: Stat
}) {
  const { theme } = useTheme()
  const colors = chartColors(theme)
  if (!chartData.length) return <div className="muted">No data.</div>
  return (
    <ResponsiveContainer width="100%" height={340}>
      <BarChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 56 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} />
        <XAxis dataKey="profile" angle={-30} textAnchor="end" height={80} interval={0} stroke={colors.axis} tick={{ fontSize: 11, fill: colors.text }} />
        <YAxis stroke={colors.axis} tick={{ fontSize: 11, fill: colors.text }} />
        <Tooltip formatter={(value: any) => (value == null ? '—' : `${Number(value).toFixed(0)} ms`)} contentStyle={colors.tooltip} labelStyle={colors.tooltipLabel} />
        <Legend />
        {chartBars.map((bar) => (
          <Bar
            key={bar.key}
            dataKey={bar.key}
            name={`${bar.key} · ${METRIC_LABELS[metric] ?? metric} ${stat}`}
            fill={bar.color}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
