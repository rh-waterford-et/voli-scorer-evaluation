import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import SortTable, { type Column } from '../components/SortTable'
import { api } from '../api'
import type { RunMeta } from '../types'
import { fmtInt, fmtWhen, isActive, statusClass } from '../format'

export default function History() {
  const navigate = useNavigate()
  const [items, setItems] = useState<RunMeta[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const load = useCallback(async () => {
    try {
      setItems(await api.runs())
      setError(null)
    } catch (cause) {
      setError(String(cause))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const anyActive = (items ?? []).some((item) => isActive(item.status))
  useEffect(() => {
    if (!anyActive) return
    const timer = setInterval(load, 4000)
    return () => clearInterval(timer)
  }, [anyActive, load])

  const toggle = (id: string) => {
    setSelected((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const remove = async (id: string) => {
    if (!window.confirm(`Delete run ${id} and its stored results?`)) return
    try {
      await api.remove(id)
      setSelected((previous) => {
        const next = new Set(previous)
        next.delete(id)
        return next
      })
      load()
    } catch (cause) {
      setError(String(cause))
    }
  }

  const columns: Column<RunMeta>[] = [
    {
      key: 'select',
      label: '',
      render: (row) => (
        <input
          type="checkbox"
          checked={selected.has(row.id)}
          onChange={() => toggle(row.id)}
          onClick={(event) => event.stopPropagation()}
        />
      ),
    },
    {
      key: 'created',
      label: 'Created',
      sort: (row) => row.created_at ?? '',
      render: (row) => (
        <Link to={`/runs/${encodeURIComponent(row.id)}`}>{fmtWhen(row.created_at)}</Link>
      ),
    },
    {
      key: 'name',
      label: 'Name',
      sort: (row) => row.name ?? '',
      render: (row) => <Link to={`/runs/${encodeURIComponent(row.id)}`}>{row.name || row.id}</Link>,
    },
    {
      key: 'source',
      label: 'Source',
      title: 'dashboard = run started from this UI · report = committed JSON under reports/ (read-only)',
      sort: (row) => row.source,
      render: (row) => <span className="chip">{row.source}</span>,
    },
    {
      key: 'status',
      label: 'Status',
      sort: (row) => row.status,
      render: (row) => <span className={statusClass(row.status)}>{row.status}</span>,
    },
    {
      key: 'model',
      label: 'Model',
      sort: (row) => row.model ?? row.summary?.profiles[0] ?? '',
      render: (row) => row.model ?? '—',
    },
    {
      key: 'profiles',
      label: 'Profiles',
      title: 'Distinct EPP profiles exercised',
      align: 'right',
      sort: (row) => row.summary?.profiles.length ?? 0,
      render: (row) => fmtInt(row.summary?.profiles.length),
    },
    {
      key: 'requests',
      label: 'Requests',
      title: 'Total requests across all profile runs',
      align: 'right',
      sort: (row) => row.summary?.requests ?? 0,
      render: (row) => fmtInt(row.summary?.requests),
    },
    {
      key: 'valid',
      label: 'Valid / Failed',
      title: 'Valid responses vs failed requests',
      align: 'right',
      sort: (row) => (row.summary?.valid ?? 0) - (row.summary?.failed ?? 0),
      render: (row) => (
        <span>
          <span style={{ color: 'var(--ok)' }}>{fmtInt(row.summary?.valid)}</span>
          {' / '}
          <span style={{ color: row.summary?.failed ? 'var(--bad)' : 'inherit' }}>
            {fmtInt(row.summary?.failed)}
          </span>
        </span>
      ),
    },
    {
      key: 'actions',
      label: '',
      render: (row) =>
        row.source === 'dashboard' ? (
          <button className="link" onClick={() => remove(row.id)} title="Delete run">
            delete
          </button>
        ) : (
          <span className="muted" title="Repository reports are read-only">
            read-only
          </span>
        ),
    },
  ]

  return (
    <div>
      <div className="page-head">
        <h1>Run history</h1>
        <div className="actions">
          <button onClick={load}>Refresh</button>
          <button
            className="primary"
            disabled={selected.size < 2}
            title={selected.size < 2 ? 'Select at least two runs' : 'Compare selected runs'}
            onClick={() => navigate(`/compare?ids=${encodeURIComponent(Array.from(selected).join(','))}`)}
          >
            Compare selected ({selected.size})
          </button>
        </div>
      </div>
      {error && <div className="error-text">{error}</div>}
      <div className="panel">
        <SortTable
          columns={columns}
          rows={items ?? []}
          rowKey={(row) => row.id}
          initialSortKey="created"
          initialDesc
          emptyText={items === null ? 'Loading…' : 'No runs yet. Start one from New Run.'}
        />
      </div>
      <p className="muted">
        Runs with source <span className="chip">report</span> are JSON files committed under{' '}
        <code>reports/</code>, shown read-only.
      </p>
    </div>
  )
}
