import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type {
  BuilderBackup,
  BuilderJob,
  BuilderPreview,
  BuilderProfile,
  BuilderState,
  ProfilesCheckResponse,
} from '../types'
import { fmtWhen } from '../format'

type Mode = 'none' | 'create' | 'edit' | 'delete'

interface DraftRow {
  name: string
  weight: number
}

function scorerText(profile: BuilderProfile): string {
  const parts = profile.scorers.map(
    (ref) => `${ref.name}${ref.weight != null ? ` (${ref.weight})` : ''}`,
  )
  const extras = profile.others.length ? ` +${profile.others.length} other` : ''
  return (parts.join(' + ') || 'no scorers') + extras
}

function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) return <div className="muted">No changes.</div>
  return (
    <pre className="log diff">
      {diff.split('\n').map((line, index) => {
        let className = ''
        if (line.startsWith('+') && !line.startsWith('+++')) className = 'add'
        else if (line.startsWith('-') && !line.startsWith('---')) className = 'del'
        else if (line.startsWith('@@')) className = 'hunk'
        return (
          <span key={index} className={className}>
            {line}
            {'\n'}
          </span>
        )
      })}
    </pre>
  )
}

function StepIcon({ status }: { status: string }) {
  switch (status) {
    case 'done':
      return <span className="step-status step-done">✓</span>
    case 'running':
      return <span className="step-status step-running">…</span>
    case 'failed':
      return <span className="step-status step-failed">✗</span>
    default:
      return <span className="step-status step-pending">·</span>
  }
}

export default function Builder() {
  const [namespace, setNamespace] = useState('vllm-omni-validation')
  const [deployment, setDeployment] = useState('endpoint-picker-epp')
  const [container, setContainer] = useState('epp')

  const [state, setState] = useState<BuilderState | null>(null)
  const [stateError, setStateError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  const [mode, setMode] = useState<Mode>('none')
  const [draftName, setDraftName] = useState('')
  const [rows, setRows] = useState<DraftRow[]>([])
  const [picker, setPicker] = useState('')

  const [preview, setPreview] = useState<BuilderPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [lastBody, setLastBody] = useState<any>(null)

  const [jobId, setJobId] = useState<string | null>(null)
  const [job, setJob] = useState<BuilderJob | null>(null)

  const [backups, setBackups] = useState<BuilderBackup[]>([])
  const [syncMessage, setSyncMessage] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [scorerCaveats, setScorerCaveats] = useState<ProfilesCheckResponse['scorers'] | null>(null)

  const loadState = useCallback(async () => {
    setLoading(true)
    setStateError(null)
    try {
      const result = await api.builderState({
        namespace,
        epp_deployment: deployment,
        epp_container: container,
      })
      setState(result)
    } catch (cause) {
      setStateError(String(cause))
      setState(null)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace, deployment, container])

  const loadBackups = useCallback(async () => {
    try {
      setBackups(await api.builderBackups())
    } catch {
      /* backups are non-fatal */
    }
  }, [])

  useEffect(() => {
    loadState()
    loadBackups()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Type-keyed scorer caveats for the composer (cross-endpoint, worst case).
  useEffect(() => {
    api
      .profileCheck('/v1/audio/speech', {
        namespace,
        epp_deployment: deployment,
        epp_container: container,
      })
      .then((check) => setScorerCaveats(check.scorers))
      .catch(() => setScorerCaveats(null))
  }, [namespace, deployment, container])

  // Poll the running job until it finishes.
  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    const tick = async () => {
      try {
        const current = await api.builderJob(jobId)
        if (!cancelled) setJob(current)
      } catch {
        /* keep polling */
      }
    }
    tick()
    if (job && job.status !== 'running') return
    const timer = setInterval(tick, 1500)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [jobId, job?.status])

  // Refresh after a finished job.
  useEffect(() => {
    if (job && job.status === 'done') {
      loadState()
      loadBackups()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status])

  const scorerInstances = useMemo(
    () => (state?.instances ?? []).filter((i) => i.kind === 'scorer'),
    [state],
  )
  const pickerInstances = useMemo(
    () => (state?.instances ?? []).filter((i) => i.kind === 'picker'),
    [state],
  )

  const resetComposer = () => {
    setMode('none')
    setDraftName('')
    setRows([])
    setPicker('')
    setPreview(null)
    setPreviewError(null)
    setConfirming(false)
    setLastBody(null)
    setJobId(null)
    setJob(null)
  }

  const startCreate = () => {
    setMode('create')
    setDraftName('')
    setRows([{ name: scorerInstances[0]?.name ?? '', weight: 1 }])
    setPicker(state?.picker_default ?? pickerInstances[0]?.name ?? '')
    setPreview(null)
    setPreviewError(null)
    setConfirming(false)
    setJobId(null)
    setJob(null)
  }

  const startEdit = (profile: BuilderProfile) => {
    setMode('edit')
    setDraftName(profile.name)
    setRows(profile.scorers.map((ref) => ({ name: ref.name, weight: ref.weight ?? 1 })))
    setPicker(profile.picker ?? state?.picker_default ?? '')
    setPreview(null)
    setPreviewError(null)
    setConfirming(false)
    setJobId(null)
    setJob(null)
  }

  const startDelete = (profile: BuilderProfile) => {
    setMode('delete')
    setDraftName(profile.name)
    setRows([])
    setPicker(profile.picker ?? '')
    setPreview(null)
    setPreviewError(null)
    setConfirming(false)
    setJobId(null)
    setJob(null)
    doPreview('delete', profile.name, [], profile.picker)
  }

  const buildBody = (
    action: Mode,
    profile: string,
    scorerRows: DraftRow[],
    pickerValue: string | null,
  ) => ({
    namespace,
    epp_deployment: deployment,
    epp_container: container,
    expected_resource_version: state?.resource_version ?? null,
    operation: {
      action,
      profile,
      scorers: scorerRows
        .filter((row) => row.name)
        .map((row) => ({ name: row.name, weight: Number(row.weight) || 1 })),
      picker: action === 'delete' ? null : pickerValue || null,
    },
  })

  const doPreview = async (
    actionOverride?: Mode,
    nameOverride?: string,
    rowsOverride?: DraftRow[],
    pickerOverride?: string | null,
  ) => {
    if (!state) return
    const action = (actionOverride ?? mode) as 'create' | 'edit' | 'delete'
    const profile = (nameOverride ?? draftName).trim()
    const scorerRows = action === 'delete' ? [] : (rowsOverride ?? rows)
    const pickerValue = action === 'delete' ? null : (pickerOverride ?? picker)
    const body = buildBody(action, profile, scorerRows, pickerValue)
    setLastBody(body)
    setPreview(null)
    setPreviewError(null)
    setConfirming(false)
    try {
      setPreview(await api.builderPreview(body))
    } catch (cause) {
      setPreviewError(String(cause))
    }
  }

  const doApply = async () => {
    if (!preview?.ok || !lastBody) return
    const body = { ...lastBody, expected_resource_version: preview.resource_version }
    try {
      const result = await api.builderApply(body)
      setConfirming(false)
      setJobId(result.job_id)
      setJob(null)
    } catch (cause) {
      setPreviewError(String(cause))
    }
  }

  const doRevert = async (backupId: string) => {
    if (
      !window.confirm(
        `Restore the config from backup ${backupId}?\n\nThe current config is saved as a new backup first, so this can itself be reverted.`,
      )
    ) {
      return
    }
    try {
      const result = await api.builderRevert(backupId)
      resetComposer()
      setJobId(result.job_id)
      setJob(null)
    } catch (cause) {
      setStateError(String(cause))
    }
  }

  const copyLiveYaml = async () => {
    try {
      const result = await api.builderLiveYaml({
        namespace,
        epp_deployment: deployment,
        epp_container: container,
      })
      await navigator.clipboard.writeText(result.text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (cause) {
      setStateError(String(cause))
    }
  }

  const syncScriptMap = async () => {
    setSyncing(true)
    setSyncMessage(null)
    try {
      const result = await api.builderSyncMap({
        namespace,
        epp_deployment: deployment,
        epp_container: container,
      })
      setSyncMessage(
        `Synced ${result.synced} profiles into scripts/${result.file} (${new Date(
          result.synced_at,
        ).toLocaleString()}). New Run's profile list now matches the cluster.`,
      )
    } catch (cause) {
      setSyncMessage(String(cause))
    } finally {
      setSyncing(false)
    }
  }

  const updateRow = (index: number, patch: Partial<DraftRow>) => {
    setRows((previous) => previous.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  const jobActive = job?.status === 'running'

  return (
    <div>
      <div className="page-head">
        <h1>Profile Builder</h1>
        <div className="actions">
          <button onClick={loadState} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
          <button onClick={copyLiveYaml} disabled={!state} title="Copy the raw live plugin YAML, e.g. to sync Helm values">
            {copied ? 'Copied ✓' : 'Copy live YAML'}
          </button>
          <button
            onClick={syncScriptMap}
            disabled={!state || syncing}
            title="Mirror the live scheduling profiles into the script's local profile map (gitignored), so New Run and CLI validation match the cluster"
          >
            {syncing ? 'Syncing…' : 'Sync script map'}
          </button>
        </div>
      </div>
      {syncMessage && <div className="muted panel">{syncMessage}</div>}

      <div className="panel">
        <h2>Live configuration</h2>
        <div className="form-grid">
          <div>
            <label>Namespace</label>
            <input type="text" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
          </div>
          <div>
            <label>EPP deployment</label>
            <input type="text" value={deployment} onChange={(e) => setDeployment(e.target.value)} />
          </div>
          <div>
            <label>EPP container</label>
            <input type="text" value={container} onChange={(e) => setContainer(e.target.value)} />
          </div>
        </div>
        {stateError && <div className="error-text">{stateError}</div>}
        {state && (
          <p className="muted">
            ConfigMap <code>{state.configmap}</code> · key <code>{state.config_key}</code> ·
            resourceVersion <code>{state.resource_version}</code> · apiVersion{' '}
            <code>{state.api_version}</code> · picker <code>{state.picker_default}</code> ·
            default profile <code>{state.default_profile}</code>
            <br />
            {state.warnings.map((warning) => (
              <span key={warning} className="warn-text">
                ⚠ {warning}
              </span>
            ))}
          </p>
        )}
        {!state && !stateError && <div className="muted">Loading…</div>}
      </div>

      {state && (
        <div className="panel">
          <h2>Scheduling profiles ({state.profiles.length})</h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Scorers &amp; weights</th>
                  <th>Picker</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {state.profiles.map((profile) => {
                  const isDefault = profile.name === state.default_profile
                  return (
                    <tr key={profile.name}>
                      <td className="mono">
                        {profile.name} {isDefault && <span className="chip">default</span>}
                      </td>
                      <td>{scorerText(profile)}</td>
                      <td className="mono">{profile.picker ?? '—'}</td>
                      <td>
                        <button className="link" onClick={() => startEdit(profile)}>
                          edit
                        </button>
                        {' · '}
                        <button
                          className="link"
                          disabled={isDefault}
                          title={
                            isDefault
                              ? "The header profile handler's default profile cannot be deleted"
                              : `Delete ${profile.name}`
                          }
                          onClick={() => startDelete(profile)}
                        >
                          delete
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="actions">
            <button className="primary" onClick={startCreate}>
              New profile
            </button>
          </div>
        </div>
      )}

      {state && (mode === 'create' || mode === 'edit') && (
        <div className="panel">
          <h2>{mode === 'create' ? 'New profile' : `Edit profile ${draftName}`}</h2>
          <div className="form-grid">
            <div>
              <label>
                Profile name
                <br />
                <span className="muted" style={{ fontWeight: 400 }}>
                  sent as the EPP-Profile header value
                </span>
              </label>
              <input
                type="text"
                value={draftName}
                disabled={mode === 'edit'}
                placeholder="e.g. queueRunningProfile"
                onChange={(e) => setDraftName(e.target.value)}
              />
            </div>
            <div>
              <label>Picker</label>
              <select value={picker} onChange={(e) => setPicker(e.target.value)}>
                {pickerInstances.map((instance) => (
                  <option key={instance.name} value={instance.name}>
                    {instance.name} ({instance.type})
                  </option>
                ))}
              </select>
            </div>
          </div>

          <h3>Scorers</h3>
          {rows.map((row, index) => (
            <div key={index} className="load-row">
              <select value={row.name} onChange={(e) => updateRow(index, { name: e.target.value })}>
                <option value="">select scorer…</option>
                {scorerInstances.map((instance) => (
                  <option key={instance.name} value={instance.name}>
                    {instance.name} ({instance.type})
                  </option>
                ))}
              </select>
              <label style={{ marginBottom: 0 }}>weight</label>
              <input
                type="number"
                min={0.1}
                step={0.5}
                value={row.weight}
                onChange={(e) => updateRow(index, { weight: Number(e.target.value) })}
              />
              <button disabled={rows.length === 1} onClick={() => setRows(rows.filter((_, i) => i !== index))}>
                remove
              </button>
            </div>
          ))}
          <div className="actions">
            <button onClick={() => setRows([...rows, { name: scorerInstances[0]?.name ?? '', weight: 1 }])}>
              add scorer
            </button>
            <button onClick={() => doPreview()} disabled={!draftName.trim()}>
              Preview
            </button>
            <button onClick={resetComposer}>Cancel</button>
          </div>
          {(() => {
            const notes = rows
              .map((row) => {
                const instance = state?.instances.find((item) => item.name === row.name)
                if (!instance) return null
                const entry = scorerCaveats?.[instance.type]
                return entry && entry.severity !== 'ok' ? { instance, entry } : null
              })
              .filter((value): value is NonNullable<typeof value> => value != null)
            if (!notes.length) return null
            return (
              <div className="warn-text">
                {notes.map((note) => (
                  <div key={note.instance.name}>
                    <span className="mono">{note.instance.name}</span> ({note.instance.type}):{' '}
                    {note.entry.reasons.join(' ')}
                  </div>
                ))}
              </div>
            )
          })()}
          <p className="muted">
            Scorers combine as a weighted sum: Σ(score × weight). Only plugin instances already
            instantiated in the live config are offered.
          </p>
        </div>
      )}

      {state && mode === 'delete' && (
        <div className="panel">
          <h2>Delete profile {draftName}</h2>
          <p className="muted">
            The profile is removed from the ConfigMap and EPP is restarted. A backup of the
            current config is saved first.
          </p>
          <div className="actions">
            <button onClick={resetComposer}>Cancel</button>
          </div>
        </div>
      )}

      {(preview || previewError) && mode !== 'none' && (
        <div className="panel">
          <h2>Preview</h2>
          {previewError && <div className="error-text">{previewError}</div>}
          {preview && (
            <>
              {preview.errors.map((error) => (
                <div key={error} className="error-text">
                  ✗ {error}
                </div>
              ))}
              {preview.warnings.map((warning) => (
                <div key={warning} className="warn-text">
                  ⚠ {warning}
                </div>
              ))}
              {preview.ok && (
                <>
                  <p>
                    <strong>{preview.summary}</strong>
                  </p>
                  <DiffView diff={preview.diff} />
                  {!confirming ? (
                    <div className="actions">
                      <button className="danger" onClick={() => setConfirming(true)}>
                        Apply to cluster…
                      </button>
                    </div>
                  ) : (
                    <div className="confirm-box">
                      <p>
                        This will patch ConfigMap <code>{preview.configmap}</code> (key{' '}
                        <code>{preview.config_key}</code>) and restart the EPP deployment. The
                        current config is saved as a backup first, and a failed rollout can be
                        reverted from it.
                      </p>
                      <div className="actions">
                        <button className="danger" onClick={doApply}>
                          Yes, apply
                        </button>
                        <button onClick={() => setConfirming(false)}>Cancel</button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>
      )}

      {job && (
        <div className="panel">
          <h2>
            {job.kind === 'revert' ? 'Restore' : 'Apply'}: {job.summary}{' '}
            <span className={`badge ${job.status === 'done' ? 'ok' : job.status === 'failed' ? 'bad' : 'running'}`}>
              {job.status}
            </span>
          </h2>
          <ul className="steps">
            {job.steps.map((step) => (
              <li key={step.key}>
                <StepIcon status={step.status} />
                <span>{step.label}</span>
                {step.detail && <span className="muted"> — {step.detail}</span>}
              </li>
            ))}
          </ul>
          {job.status === 'failed' && job.error && <div className="error-text">{job.error}</div>}
          {job.status === 'failed' && job.revert_available && job.backup_id && (
            <div className="warn-text">
              The ConfigMap was patched but the rollout did not succeed. You can restore the
              previous config from backup {job.backup_id}.
              <div className="actions">
                <button className="danger" onClick={() => doRevert(job.backup_id!)} disabled={jobActive}>
                  Revert to backup
                </button>
              </div>
            </div>
          )}
          {job.status === 'done' && (
            <div className="actions">
              {job.kind === 'apply' && mode !== 'delete' && draftName && (
                <Link className="button-link" to={`/new?profile=${encodeURIComponent(draftName)}`}>
                  Test this profile in a new run →
                </Link>
              )}
              <button onClick={resetComposer}>Back to profiles</button>
            </div>
          )}
        </div>
      )}

      <div className="panel">
        <h2>Backups</h2>
        <p className="muted">
          Each backup stores the config as it was <em>before</em> the labeled operation ran.
          Restoring first saves the current config as a new backup, so restores can be undone.
        </p>
        {!backups.length && <div className="muted">No backups yet.</div>}
        {!!backups.length && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Config before</th>
                  <th>ConfigMap</th>
                  <th>ResourceVersion</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {backups.map((backup) => (
                  <tr key={backup.id}>
                    <td>{fmtWhen(backup.created_at)}</td>
                    <td>{backup.operation}</td>
                    <td className="mono">
                      {backup.configmap}/{backup.config_key}
                    </td>
                    <td className="num">{backup.resource_version}</td>
                    <td>
                      <button
                        className="link"
                        disabled={jobActive}
                        onClick={() => doRevert(backup.id)}
                        title={`Restore the config as it was before: ${backup.operation}`}
                      >
                        restore
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
