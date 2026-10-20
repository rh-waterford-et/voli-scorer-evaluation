import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import SortTable, { type Column } from '../components/SortTable'
import { EppScoreView, Histogram, MetricBarChart } from '../components/Charts'
import { api, openRunEvents } from '../api'
import type { RequestResult, RunDetail, ScriptRun } from '../types'
import {
  METRIC_LABELS,
  METRIC_ORDER,
  fmtDuration,
  fmtInt,
  fmtMs,
  fmtPercent,
  fmtWhen,
  isActive,
  loadLabel,
  shortPod,
  statusClass,
} from '../format'

function metricOf(run: ScriptRun, metric: string, stat: 'mean' | 'p50' | 'p99') {
  return run.metrics?.[metric]?.[stat] ?? null
}

function RoutingTable({ run }: { run: ScriptRun }) {
  const total = Object.values(run.routing).reduce((a, b) => a + b, 0)
  const entries = Object.entries(run.routing).sort((a, b) => b[1] - a[1])
  if (!entries.length) return <div className="muted">No routing data.</div>
  return (
    <table className="data">
      <thead>
        <tr>
          <th>Pod</th>
          <th className="num">Count</th>
          <th className="num">Share</th>
          <th style={{ width: 200 }} />
        </tr>
      </thead>
      <tbody>
        {entries.map(([pod, count]) => (
          <tr key={pod}>
            <td className="mono">{shortPod(pod)}</td>
            <td className="num">{count}</td>
            <td className="num">{fmtPercent(count, total)}</td>
            <td>
              <div className="bar-track">
                <div className="bar" style={{ width: `${total ? (count / total) * 100 : 0}%` }} />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function FullMetricsTable({ run }: { run: ScriptRun }) {
  const keys = METRIC_ORDER.filter((key) => (run.metrics?.[key]?.n ?? 0) > 0)
  if (!keys.length) return <div className="muted">No latency samples.</div>
  return (
    <table className="data">
      <thead>
        <tr>
          <th>Metric</th>
          <th className="num">N</th>
          <th className="num">Mean</th>
          <th className="num">P50</th>
          <th className="num">P99</th>
        </tr>
      </thead>
      <tbody>
        {keys.map((key) => (
          <tr key={key}>
            <td>{METRIC_LABELS[key] ?? key}</td>
            <td className="num">{run.metrics[key].n}</td>
            <td className="num">{fmtMs(run.metrics[key].mean)}</td>
            <td className="num">{fmtMs(run.metrics[key].p50)}</td>
            <td className="num">{fmtMs(run.metrics[key].p99)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SessionSummary({ run }: { run: ScriptRun }) {
  const replay = run.session_replay
  if (!replay) return null
  return (
    <div>
      <h3>Session replay</h3>
      <p className="muted">
        {replay.sessions} sessions (up to {replay.concurrent_sessions} concurrent, length{' '}
        {replay.session_length}) · header <code>{replay.header}</code> ·{' '}
        {replay.replayed_requests}/{replay.followup_requests} follow-ups replayed a token ·
        routing on replay: {replay.same_pod} same pod, {replay.changed_pod} changed,{' '}
        {replay.unresolved_pod} unresolved
      </p>
      {Object.entries(replay.latency).map(([group, metrics]) => (
        <p key={group} className="muted">
          {group} E2E: mean {fmtMs(metrics.e2e_ms?.mean)} ms · p50 {fmtMs(metrics.e2e_ms?.p50)} ms ·
          p99 {fmtMs(metrics.e2e_ms?.p99)} ms (N={metrics.e2e_ms?.n ?? 0})
        </p>
      ))}
    </div>
  )
}

function RequestsTable({ run }: { run: ScriptRun }) {
  const requests = run.results ?? []
  if (!requests.length) return <div className="muted">No per-request details stored.</div>
  const columns: Column<RequestResult>[] = [
    { key: 'iteration', label: '#', sort: (r) => r.iteration, render: (r) => r.iteration },
    {
      key: 'status',
      label: 'Status',
      sort: (r) => r.status,
      render: (r) =>
        r.status === 'ok' ? (
          <span className="badge ok">ok</span>
        ) : (
          <span className="badge bad" title={r.error ?? undefined}>
            {r.error ? 'failed' : r.status}
          </span>
        ),
    },
    { key: 'pod', label: 'Pod', sort: (r) => r.pod ?? '', render: (r) => <span className="mono">{shortPod(r.pod)}</span> },
    { key: 'ttfa', label: 'TTFA ms', align: 'right', sort: (r) => r.ttfa_ms ?? null, render: (r) => fmtMs(r.ttfa_ms) },
    { key: 'ttft', label: 'TTFT ms', align: 'right', sort: (r) => r.ttft_ms ?? null, render: (r) => fmtMs(r.ttft_ms) },
    { key: 'e2e', label: 'E2E ms', align: 'right', sort: (r) => r.e2e_ms ?? null, render: (r) => fmtMs(r.e2e_ms) },
    {
      key: 'epp',
      label: 'EPP scores',
      render: (r) => (r.epp_scores ? <span className="chip">{r.epp_scores.status}</span> : '—'),
    },
  ]
  return (
    <SortTable
      columns={columns}
      rows={requests}
      rowKey={(r) => `${r.iteration}`}
      initialSortKey="iteration"
      expand={(r) => (
        <div>
          {r.error && <div className="error-text">Error: {r.error}</div>}
          {r.missing_modalities?.length ? (
            <div className="warn-text">Missing modalities: {r.missing_modalities.join(', ')}</div>
          ) : null}
          {r.session_id && (
            <div className="muted">
              {r.session_id} · turn {r.session_turn} ·{' '}
              {r.session_token_sent ? 'replayed token' : 'no token'}
            </div>
          )}
          {r.epp_scores && <EppScoreView record={r.epp_scores} />}
        </div>
      )}
    />
  )
}

function RunDetailPanel({ run }: { run: ScriptRun }) {
  return (
    <div className="run-detail">
      <h3>Latency metrics</h3>
      <FullMetricsTable run={run} />
      <h3>Routing</h3>
      <RoutingTable run={run} />
      {run.epp_scores && (
        <>
          <h3>EPP score collection</h3>
          <p className="muted">
            Coverage: {Object.entries(run.epp_scores.coverage).map(([k, v]) => `${v} ${k}`).join(', ') || 'none'}
            {run.epp_scores.warnings?.length ? (
              <span className="warn-text"> · warnings: {run.epp_scores.warnings.join('; ')}</span>
            ) : null}
          </p>
        </>
      )}
      <SessionSummary run={run} />
      <h3>Requests</h3>
      <RequestsTable run={run} />
    </div>
  )
}

export default function RunView() {
  const { id = '' } = useParams()
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [logLines, setLogLines] = useState<string[]>([])
  const [progress, setProgress] = useState<{ profile: string; scorer: string; iterations: number; concurrency: number } | null>(null)
  const [chartMetric, setChartMetric] = useState('e2e_ms')
  const [histoMetric, setHistoMetric] = useState('e2e_ms')
  const [histoRunId, setHistoRunId] = useState('')
  const logRef = useRef<HTMLPreElement | null>(null)
  const sourceRef = useRef<EventSource | null>(null)

  const load = useCallback(async () => {
    try {
      const result = await api.run(id)
      setDetail(result)
      setError(null)
    } catch (cause) {
      setError(String(cause))
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const status = detail?.status
  useEffect(() => {
    if (!detail || !isActive(status)) return
    sourceRef.current?.close()
    const source = openRunEvents(
      id,
      {
        snapshot: (data: any) => {
          if (data?.meta) setDetail(data.meta)
          setLogLines(data?.log_tail ?? [])
        },
        log: (data: any) => {
          if (data?.line != null) setLogLines((previous) => [...previous.slice(-500), data.line])
        },
        progress: (data: any) => setProgress(data),
        profile: () => load(),
      },
      () => load(),
    )
    sourceRef.current = source
    return () => {
      source.close()
      sourceRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, status])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logLines])

  const runs = detail?.results?.runs ?? []
  const metricKeys = useMemo(
    () => METRIC_ORDER.filter((key) => runs.some((run) => (run.metrics?.[key]?.n ?? 0) > 0)),
    [runs],
  )
  const hasAudio = runs.some((run) => (run.metrics?.ttfa_ms?.n ?? 0) > 0)
  const hasText = runs.some((run) => (run.metrics?.ttft_ms?.n ?? 0) > 0)

  useEffect(() => {
    if (!metricKeys.length) return
    if (!metricKeys.includes(chartMetric)) {
      setChartMetric(metricKeys.includes('e2e_ms') ? 'e2e_ms' : metricKeys[metricKeys.length - 1])
    }
    if (!metricKeys.includes(histoMetric)) setHistoMetric(chartMetric)
    if (!runs.some((run) => run.run_id === histoRunId)) {
      setHistoRunId(runs.length ? runs[0].run_id : '')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metricKeys])

  const columns: Column<ScriptRun>[] = [
    {
      key: 'profile',
      label: 'Profile',
      sort: (r) => r.profile,
      render: (r) => <strong className="mono">{r.profile}</strong>,
    },
    { key: 'scorer', label: 'Scorer', sort: (r) => r.scorer, render: (r) => <span className="muted">{r.scorer}</span> },
    { key: 'load', label: 'Load', sort: (r) => r.concurrency, render: (r) => loadLabel(r) },
    {
      key: 'valid',
      label: 'Valid',
      align: 'right',
      sort: (r) => r.valid_responses,
      render: (r) => (
        <span>
          <span style={{ color: 'var(--ok)' }}>{r.valid_responses}</span>
          <span className="muted">/{r.iterations}</span>
        </span>
      ),
    },
    {
      key: 'failed',
      label: 'Failed',
      align: 'right',
      sort: (r) => r.failed_responses,
      render: (r) => (
        <span style={{ color: r.failed_responses ? 'var(--bad)' : 'inherit' }}>{r.failed_responses}</span>
      ),
    },
    { key: 'duration', label: 'Duration', align: 'right', sort: (r) => r.duration_seconds, render: (r) => fmtDuration(r.duration_seconds) },
  ]
  if (hasAudio) {
    columns.push(
      { key: 'ttfa_p50', label: 'TTFA p50', align: 'right', sort: (r) => metricOf(r, 'ttfa_ms', 'p50'), render: (r) => fmtMs(metricOf(r, 'ttfa_ms', 'p50')) },
      { key: 'ttfa_p99', label: 'TTFA p99', align: 'right', sort: (r) => metricOf(r, 'ttfa_ms', 'p99'), render: (r) => fmtMs(metricOf(r, 'ttfa_ms', 'p99')) },
    )
  }
  if (hasText) {
    columns.push(
      { key: 'ttft_p50', label: 'TTFT p50', align: 'right', sort: (r) => metricOf(r, 'ttft_ms', 'p50'), render: (r) => fmtMs(metricOf(r, 'ttft_ms', 'p50')) },
      { key: 'ttft_p99', label: 'TTFT p99', align: 'right', sort: (r) => metricOf(r, 'ttft_ms', 'p99'), render: (r) => fmtMs(metricOf(r, 'ttft_ms', 'p99')) },
      { key: 'tpot', label: 'TPOT~ mean', align: 'right', sort: (r) => metricOf(r, 'tpot_estimate_ms', 'mean'), render: (r) => fmtMs(metricOf(r, 'tpot_estimate_ms', 'mean')) },
    )
  }
  columns.push(
    { key: 'e2e_mean', label: 'E2E mean', align: 'right', sort: (r) => metricOf(r, 'e2e_ms', 'mean'), render: (r) => fmtMs(metricOf(r, 'e2e_ms', 'mean')) },
    { key: 'e2e_p50', label: 'E2E p50', align: 'right', sort: (r) => metricOf(r, 'e2e_ms', 'p50'), render: (r) => fmtMs(metricOf(r, 'e2e_ms', 'p50')) },
    { key: 'e2e_p99', label: 'E2E p99', align: 'right', sort: (r) => metricOf(r, 'e2e_ms', 'p99'), render: (r) => fmtMs(metricOf(r, 'e2e_ms', 'p99')) },
  )

  const chartData = runs.map((run) => ({
    label: `${run.profile} ${loadLabel(run)}`,
    p50: metricOf(run, chartMetric, 'p50'),
    p99: metricOf(run, chartMetric, 'p99'),
  }))

  const histoRun = runs.find((run) => run.run_id === histoRunId)
  const histoValues =
    histoRun?.results
      ?.map((request) =>
        histoMetric === 'e2e_ms' ? request.e2e_ms : (request as any)[histoMetric] ?? null,
      )
      .filter((value): value is number => value != null) ?? []

  const cancel = async () => {
    try {
      await api.cancel(id)
      load()
    } catch (cause) {
      setError(String(cause))
    }
  }

  if (error && !detail) {
    return (
      <div>
        <h1>Run</h1>
        <div className="error-text panel">{error}</div>
      </div>
    )
  }
  if (!detail) return <div className="muted">Loading…</div>

  const params = detail.params

  return (
    <div>
      <div className="page-head">
        <h1>
          {detail.name || detail.id}{' '}
          <span className={statusClass(detail.status)}>{detail.status}</span>
        </h1>
        <div className="actions">
          {isActive(detail.status) && (
            <button className="danger" onClick={cancel}>Cancel run</button>
          )}
        </div>
      </div>

      <div className="panel">
        <p className="muted">
          {detail.source === 'report' ? (
            <>Repository report <code>reports/{detail.name}.json</code></>
          ) : (
            <>Started {fmtWhen(detail.created_at)}{detail.finished_at ? ` · finished ${fmtWhen(detail.finished_at)}` : ''}</>
          )}
          {detail.results && (
            <>
              {' '}· model <code>{detail.results.model ?? '—'}</code>
              {' '}· endpoint <code>{detail.results.endpoint ?? params?.endpoint ?? '—'}</code>
              {' '}· modalities <code>{(detail.results.modalities ?? []).join(',') || '—'}</code>
            </>
          )}
          {params && (
            <>
              {' '}· gateway <code>{params.url}</code>
              {' '}· namespace <code>{params.namespace}</code>
            </>
          )}
        </p>
        {detail.error && <div className="warn-text">{detail.error}</div>}
      </div>

      {isActive(detail.status) && (
        <div className="panel">
          <h2>Live progress</h2>
          {detail.profiles && (
            <p className="muted">
              {detail.profiles.map((attempt, index) => (
                <span key={attempt.name} style={{ marginRight: 12 }}>
                  {index + 1}. <span className="mono">{attempt.name}</span>{' '}
                  <span className={statusClass(attempt.status)}>{attempt.status}</span>
                </span>
              ))}
            </p>
          )}
          {progress && (
            <p>
              <span className="mono">{progress.profile}</span> ({progress.scorer}):{' '}
              {progress.iterations} requests, concurrency {progress.concurrency}…
            </p>
          )}
          <pre className="log" ref={logRef}>{logLines.slice(-300).join('\n') || 'waiting for output…'}</pre>
        </div>
      )}

      {detail.source === 'dashboard' && !isActive(detail.status) && logLines.length === 0 && detail.status !== 'completed' && (
        <div className="panel muted">This run has no captured log (it may have failed before starting).</div>
      )}

      {runs.length > 0 && (
        <>
          <div className="panel">
            <h2>Results by profile and load</h2>
            <p className="muted">
              Click a column header to sort (click again to reverse); expand a row for full
              metrics, routing, scores, and per-request details.
            </p>
            <SortTable
              columns={columns}
              rows={runs}
              rowKey={(run) => run.run_id}
              initialSortKey="e2e_p50"
              expand={(run) => <RunDetailPanel run={run} />}
            />
          </div>

          <div className="panel">
            <h2>Comparison chart</h2>
            <div className="actions">
              <label>
                Metric{' '}
                <select value={chartMetric} onChange={(e) => setChartMetric(e.target.value)}>
                  {metricKeys.map((key) => (
                    <option key={key} value={key}>{METRIC_LABELS[key] ?? key}</option>
                  ))}
                </select>
              </label>
            </div>
            <MetricBarChart data={chartData} />
          </div>

          <div className="panel">
            <h2>Latency distribution</h2>
            <div className="actions">
              <label>
                Run{' '}
                <select value={histoRunId} onChange={(e) => setHistoRunId(e.target.value)}>
                  {runs.map((run) => (
                    <option key={run.run_id} value={run.run_id}>
                      {run.profile} {loadLabel(run)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Metric{' '}
                <select value={histoMetric} onChange={(e) => setHistoMetric(e.target.value)}>
                  {metricKeys.map((key) => (
                    <option key={key} value={key}>{METRIC_LABELS[key] ?? key}</option>
                  ))}
                </select>
              </label>
            </div>
            <Histogram values={histoValues} />
          </div>
        </>
      )}

      {!isActive(detail.status) && runs.length === 0 && (
        <div className="panel muted">No results stored for this run.</div>
      )}
    </div>
  )
}
