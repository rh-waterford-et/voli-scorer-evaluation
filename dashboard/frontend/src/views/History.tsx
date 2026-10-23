import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import SortTable, { type Column } from '../components/SortTable'
import { api } from '../api'
import type { RunDetail, RunMeta } from '../types'
import { fmtInt, fmtWhen, isActive, loadLabel, statusClass } from '../format'

// Selection items are `${runId}@${profile}`: comparison works at the level of
// one scheduling profile within one run. Standalone runs contribute their
// single profile directly; suite runs expand so individual profiles can be
// selected.
const itemKey = (runId: string, profile: string) => `${runId}@${profile}`

function profilesOf(row: RunMeta): string[] {
  if (row.requested_profiles?.length) return row.requested_profiles
  return row.summary?.profiles ?? []
}

function isSuite(row: RunMeta): boolean {
  return profilesOf(row).length > 1
}

interface ChildProfile {
  name: string
  scorer: string | null
  loads: string[]
  valid: number
  failed: number
}

function childrenFromDetail(detail: RunDetail): ChildProfile[] {
  const order: string[] = []
  const byName = new Map<string, ChildProfile>()
  for (const run of detail.results?.runs ?? []) {
    let child = byName.get(run.profile)
    if (!child) {
      child = { name: run.profile, scorer: run.scorer, loads: [], valid: 0, failed: 0 }
      byName.set(run.profile, child)
      order.push(run.profile)
    }
    child.loads.push(loadLabel(run))
    child.valid += run.valid_responses
    child.failed += run.failed_responses
  }
  return order.map((name) => byName.get(name)!)
}

function SuiteChildren({
  row,
  detail,
  loading,
  error,
  ensure,
  selected,
  toggleItem,
}: {
  row: RunMeta
  detail: RunDetail | null
  loading: boolean
  error: string | null
  ensure: (id: string) => void
  selected: Set<string>
  toggleItem: (runId: string, profile: string) => void
}) {
  useEffect(() => {
    ensure(row.id)
  }, [row.id]) // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <div className="error-text">{error}</div>
  if (!detail) return <div className="muted">{loading ? 'Loading profiles…' : ' '}</div>
  const children = childrenFromDetail(detail)
  if (!children.length) return <div className="muted">No profile results stored yet.</div>
  return (
    <div className="suite-children">
      {children.map((child) => {
        const key = itemKey(row.id, child.name)
        return (
          <label key={child.name} className="suite-child">
            <input
              type="checkbox"
              checked={selected.has(key)}
              onChange={() => toggleItem(row.id, child.name)}
            />
            <span className="mono">{child.name}</span>
            <span className="muted profile-scorers">{child.scorer ?? ''}</span>
            <span className="muted">loads {child.loads.join(', ')}</span>
            <span className="muted">
              valid {fmtInt(child.valid)} / failed {fmtInt(child.failed)}
            </span>
          </label>
        )
      })}
    </div>
  )
}

export default function History() {
  const navigate = useNavigate()
  const [items, setItems] = useState<RunMeta[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const [suiteDetails, setSuiteDetails] = useState<Record<string, RunDetail>>({})
  const [suiteLoading, setSuiteLoading] = useState<Set<string>>(new Set())
  const [suiteErrors, setSuiteErrors] = useState<Record<string, string>>({})

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

  const ensureDetail = useCallback(
    (id: string) => {
      if (suiteDetails[id] || suiteLoading.has(id) || suiteErrors[id]) return
      setSuiteLoading((previous) => new Set(previous).add(id))
      api
        .run(id)
        .then((detail) => setSuiteDetails((previous) => ({ ...previous, [id]: detail })))
        .catch((cause) => setSuiteErrors((previous) => ({ ...previous, [id]: String(cause) })))
        .finally(() =>
          setSuiteLoading((previous) => {
            const next = new Set(previous)
            next.delete(id)
            return next
          }),
        )
    },
    [suiteDetails, suiteLoading, suiteErrors],
  )

  const toggleItem = (runId: string, profile: string) => {
    setSelected((previous) => {
      const next = new Set(previous)
      const key = itemKey(runId, profile)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const toggleRun = (row: RunMeta) => {
    const keys = profilesOf(row).map((profile) => itemKey(row.id, profile))
    if (!keys.length) return
    setSelected((previous) => {
      const next = new Set(previous)
      const allSelected = keys.every((key) => next.has(key))
      for (const key of keys) {
        if (allSelected) next.delete(key)
        else next.add(key)
      }
      return next
    })
  }

  const selectedRunIds = () =>
    Array.from(new Set(Array.from(selected).map((key) => key.split('@')[0])))

  const remove = async (id: string) => {
    if (!window.confirm(`Delete run ${id} and its stored results?`)) return
    try {
      await api.remove(id)
      setSelected((previous) => {
        const next = new Set(previous)
        for (const key of Array.from(next)) {
          if (key.split('@')[0] === id) next.delete(key)
        }
        return next
      })
      load()
    } catch (cause) {
      setError(String(cause))
    }
  }

  const removeSelected = async () => {
    const runIds = selectedRunIds()
    if (!runIds.length) return
    if (
      !window.confirm(
        `Delete ${runIds.length} run${runIds.length > 1 ? 's' : ''} and their stored results?` +
          '\n\nWhole runs are deleted, including profiles you did not select.',
      )
    ) {
      return
    }
    const results = await Promise.allSettled(runIds.map((id) => api.remove(id)))
    const failures = results
      .map((result, index) =>
        result.status === 'rejected' ? `${runIds[index]}: ${result.reason}` : null,
      )
      .filter((value): value is string => value != null)
    if (failures.length) setError(failures.join('\n'))
    setSelected(new Set())
    load()
  }

  const compareSelected = () => {
    const itemsParam = Array.from(selected).map(encodeURIComponent).join(',')
    navigate(`/compare?items=${itemsParam}`)
  }

  const columns: Column<RunMeta>[] = [
    {
      key: 'select',
      label: '',
      render: (row) => {
        const keys = profilesOf(row).map((profile) => itemKey(row.id, profile))
        const selectedCount = keys.filter((key) => selected.has(key)).length
        const all = keys.length > 0 && selectedCount === keys.length
        const some = selectedCount > 0 && !all
        return (
          <input
            type="checkbox"
            checked={all}
            ref={(element) => {
              if (element) element.indeterminate = some
            }}
            onChange={() => toggleRun(row)}
            onClick={(event) => event.stopPropagation()}
            title={
              keys.length > 1
                ? `Select all ${keys.length} profiles in this suite run`
                : 'Select this profile for comparison'
            }
          />
        )
      },
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
      render: (row) => {
        const profileCount = profilesOf(row).length
        return (
          <Link to={`/runs/${encodeURIComponent(row.id)}`}>
            {row.name || row.id}
            {profileCount > 1 && (
              <>
                {' '}
                <span
                  className="chip"
                  title={`Benchmarks ${profileCount} profiles — expand to select individual profiles for comparison`}
                >
                  suite
                </span>
              </>
            )}
          </Link>
        )
      },
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
      align: 'right',
      title: 'Distinct EPP profiles exercised',
      sort: (row) => profilesOf(row).length,
      render: (row) => fmtInt(profilesOf(row).length),
    },
    {
      key: 'requests',
      label: 'Requests',
      align: 'right',
      title: 'Total requests across all profile runs',
      sort: (row) => row.summary?.requests ?? 0,
      render: (row) => fmtInt(row.summary?.requests),
    },
    {
      key: 'valid',
      label: 'Valid / Failed',
      align: 'right',
      title: 'Valid responses vs failed requests',
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
      render: (row) => (
        <button
          className="link"
          onClick={() => remove(row.id)}
          title={
            row.source === 'report'
              ? 'Delete reports/' + row.id.slice('report:'.length) + '.json from the working tree (commit to make permanent)'
              : 'Delete this run and its stored results'
          }
        >
          delete
        </button>
      ),
    },
  ]

  const suiteRowCount = selectedRunIds().length

  return (
    <div>
      <div className="page-head">
        <h1>Run history</h1>
        <div className="actions">
          <button onClick={load}>Refresh</button>
          <button
            className="primary"
            disabled={selected.size < 2}
            title={
              selected.size < 2
                ? 'Select at least two profiles (expand suite runs to pick individual profiles)'
                : 'Compare the selected profiles'
            }
            onClick={compareSelected}
          >
            Compare selected ({selected.size})
          </button>
          <button
            className="danger"
            disabled={!selected.size}
            title="Delete the whole runs touched by the current selection, including profiles you did not select."
            onClick={removeSelected}
          >
            Delete selected ({suiteRowCount} run{suiteRowCount === 1 ? '' : 's'})
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
          expandable={isSuite}
          expand={(row) => (
            <SuiteChildren
              row={row}
              detail={suiteDetails[row.id] ?? null}
              loading={suiteLoading.has(row.id)}
              error={suiteErrors[row.id] ?? null}
              ensure={ensureDetail}
              selected={selected}
              toggleItem={toggleItem}
            />
          )}
          emptyText={items === null ? 'Loading…' : 'No runs yet. Start one from New Run.'}
        />
      </div>
      <p className="muted">
        Selection is per scheduling profile: standalone runs select directly, and runs marked{' '}
        <span className="chip">suite</span> expand to their individual profiles (each with one or
        more scorers). Suite rows also have a select-all checkbox. Deleting always removes whole
        runs.
      </p>
    </div>
  )
}
