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

interface SelectedItem {
  runId: string
  profile: string
}

// Items are `${runId}@${profile}` — the comparison unit is one scheduling
// profile within one run, so profiles from suite runs and standalone runs
// can be mixed freely.
function parseItems(raw: string | null): SelectedItem[] {
  return (raw ?? '')
    .split(',')
    .filter(Boolean)
    .map((entry) => decodeURIComponent(entry))
    .map((entry) => {
      const separator = entry.indexOf('@')
      if (separator < 0) return null
      return { runId: entry.slice(0, separator), profile: entry.slice(separator + 1) }
    })
    .filter((item): item is SelectedItem => item != null && !!item.runId && !!item.profile)
}

function shortLabel(detail: RunDetail, index: number): string {
  const base = (detail.name || detail.id).replace(/\s+/g, ' ').slice(0, 18)
  return `${index + 1}: ${base}`
}

export default function Compare() {
  const [searchParams] = useSearchParams()
  const items = useMemo(() => parseItems(searchParams.get('items')), [searchParams])
  const runIds = useMemo(() => Array.from(new Set(items.map((item) => item.runId))), [items])

  const [runsById, setRunsById] = useState<Record<string, RunDetail>>({})
  const [error, setError] = useState<string | null>(null)
  const [metric, setMetric] = useState('e2e_ms')
  const [stat, setStat] = useState<Stat>('p50')
  const [load, setLoad] = useState('')
  const [scorerCheck, setScorerCheck] = useState<ProfilesCheckResponse | null>(null)

  useEffect(() => {
    if (!runIds.length) return
    setRunsById({})
    Promise.all(runIds.map((id) => api.run(id)))
      .then((results) => {
        const map: Record<string, RunDetail> = {}
        for (const detail of results) map[detail.id] = detail
        setRunsById(map)
        setError(null)
      })
      .catch((cause) => setError(String(cause)))
  }, [runIds])

  const details = useMemo(
    () =>
      runIds
        .map((id) => runsById[id])
        .filter((detail): detail is RunDetail => detail != null && !!detail.results?.runs?.length),
    [runIds, runsById],
  )

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

  const isItemSelected = (runId: string, profile: string) =>
    items.some((item) => item.runId === runId && item.profile === profile)

  const selectedRunsOf = (detail: RunDetail): ScriptRun[] =>
    (detail.results?.runs ?? []).filter((run) => isItemSelected(detail.id, run.profile))

  const allRuns = useMemo(
    () => details.flatMap((detail) => selectedRunsOf(detail)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [details, items],
  )
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
    selectedRunsOf(detail).find((run) => run.profile === profile && loadLabel(run) === load)

  const cellValue = (detail: RunDetail, profile: string): number | null => {
    const run = findRun(detail, profile)
    return run ? run.metrics?.[metric]?.[stat] ?? null : null
  }

  // Confounders that can dominate latency differences between runs. Runs
  // without stored settings count as unknown and only confirmed differences
  // (two or more distinct known values) warn.
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
    for (const run of allRuns) {
      const check = scorerCheck.profiles[run.profile]
      if (!check || check.severity === 'ok') continue
      if (check.severity === 'bad') inoperableProfiles.add(run.profile)
      else caveatedProfiles.set(run.profile, check)
    }
  }
  if (inoperableProfiles.size) {
    mismatched.push(`scorer operability (${Array.from(inoperableProfiles).join(', ')})`)
  }
  const operabilityBlocked = inoperableProfiles.size > 0
  const settingsMismatched = mismatched.length > (operabilityBlocked ? 1 : 0)
  const comparable = mismatched.length === 0

  // Profiles selected from suite runs: measured alongside other profiles, so
  // sequential-execution effects (warm caches, varying load) may apply.
  const suiteRunLabels = details
    .map((detail, index) => ({ detail, index }))
    .filter(
      ({ detail }) =>
        new Set((detail.results?.runs ?? []).map((run) => run.profile)).size > 1,
    )
    .map(({ detail, index }) => shortLabel(detail, index))

  // Latency-like metrics: lower is better. Winner highlighting is suppressed
  // while the runs differ in a confounder (prompt, session, model, ...).
  // A profile only has a "winner" when it has values in two or more runs at
  // the selected load; when no profile does (typical one-profile-per-run
  // comparisons), the single best value overall is highlighted instead.
  const isLowerBetter = !metric.startsWith('unknown')
  const bestByProfile = new Map<string, number>()
  let globalBestValue: number | null = null
  if (isLowerBetter && comparable) {
    for (const profile of profiles) {
      const values = details
        .map((detail) => cellValue(detail, profile))
        .filter((value): value is number => value != null)
      if (values.length > 1) bestByProfile.set(profile, Math.min(...values))
    }
    if (!bestByProfile.size) {
      for (const profile of profiles) {
        for (const detail of details) {
          const value = cellValue(detail, profile)
          if (value != null && (globalBestValue == null || value < globalBestValue)) {
            globalBestValue = value
          }
        }
      }
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

  if (!items.length) {
    return (
      <div>
        <h1>Compare runs</h1>
        <div className="panel muted">
          Select profiles in the History view (expand suite runs to pick individual profiles),
          then click "Compare selected".
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

      {suiteRunLabels.length > 0 && (
        <div className="panel warn-text">
          <strong>Measured within suite runs:</strong> {suiteRunLabels.join(', ')} benchmark
          multiple profiles sequentially, so these values may carry execution-order effects
          (warm caches, varying cluster load). They remain comparable — just treat small
          differences with care, and prefer repeated runs when a verdict matters.
        </div>
      )}

      <div className="panel">
        <div className="actions">
          <label>
            Metric
            <HelpHint text="Which latency metric to compare across the selected profiles." />
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
                      const isBest =
                        value != null &&
                        ((best != null && Math.abs(value - best) < 1e-9) ||
                          (globalBestValue != null && Math.abs(value - globalBestValue) < 1e-9))
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
            bestByProfile.size ? (
              <>
                Highlighted cells are the best (lowest) value for that profile across runs at
                load {load || '—'}.
              </>
            ) : (
              <>
                No profile appears in more than one run at this load, so the single best value
                overall is highlighted.
              </>
            )
          ) : (
            <>
              Winner highlighting is disabled because the runs differ in {mismatched.join(', ')}.
            </>
          )}{' '}
          Empty cells are not part of the selection or have no data at the chosen load.
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
