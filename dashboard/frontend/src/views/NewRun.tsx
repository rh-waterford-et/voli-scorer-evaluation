import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import HelpHint from '../components/HelpHint'
import type { ClusterProfiles, ProfileInfo } from '../types'

interface Load {
  iterations: number
  concurrency: number
}

const DEFAULTS = {
  url: 'http://10.6.62.51:31670',
  namespace: 'vllm-omni-validation',
  eppDeployment: 'endpoint-picker-epp',
  eppContainer: 'epp',
}

function profileSubText(profile: ProfileInfo): string {
  const scorerText = profile.scorers
    .map((s) => `${s.type}${s.weight != null ? ` (${s.weight})` : ''}`)
    .join(' + ')
  if (profile.name === 'default') {
    return `sends no EPP-Profile header — cluster's default profile${
      scorerText ? ` (${scorerText})` : ''
    }`
  }
  return scorerText || 'no scorers'
}

export default function NewRun() {
  const navigate = useNavigate()

  const [name, setName] = useState('')
  const [endpoint, setEndpoint] = useState<'/v1/audio/speech' | '/v1/chat/completions'>('/v1/audio/speech')
  const [model, setModel] = useState('qwen3-tts')
  const [url, setUrl] = useState(DEFAULTS.url)
  const [namespace, setNamespace] = useState(DEFAULTS.namespace)
  const [eppDeployment, setEppDeployment] = useState(DEFAULTS.eppDeployment)
  const [eppContainer, setEppContainer] = useState(DEFAULTS.eppContainer)

  const [profileInfos, setProfileInfos] = useState<ProfileInfo[]>([])
  const [profileError, setProfileError] = useState<string | null>(null)
  const [clusterInfo, setClusterInfo] = useState<ClusterProfiles | null>(null)
  const [loadingProfiles, setLoadingProfiles] = useState(false)
  const [profileSearch, setProfileSearch] = useState('')
  const [selectedProfiles, setSelectedProfiles] = useState<Set<string>>(new Set())

  const [loads, setLoads] = useState<Load[]>([{ iterations: 10, concurrency: 1 }])

  const [promptMode, setPromptMode] = useState<'single' | 'multi'>('single')
  const [prompt, setPrompt] = useState('')
  const [promptsText, setPromptsText] = useState('')

  const [modalities, setModalities] = useState('text,audio')
  const [tokenizer, setTokenizer] = useState('')
  const [voice, setVoice] = useState('')
  const [audioFormat, setAudioFormat] = useState('')

  const [sessionLength, setSessionLength] = useState(0)
  const [sessionHeader, setSessionHeader] = useState('x-session-token')

  const [eppScores, setEppScores] = useState(false)
  const [noBackendLookup, setNoBackendLookup] = useState(false)
  const [gatewayWait, setGatewayWait] = useState(10)
  const [eppWait, setEppWait] = useState(5)
  const [timeoutSeconds, setTimeoutSeconds] = useState(600)
  const [apiKey, setApiKey] = useState('')

  const [preview, setPreview] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .builtinProfiles()
      .then((result) => setProfileInfos(result.profiles))
      .catch((cause) => setProfileError(String(cause)))
  }, [])

  const loadFromCluster = async () => {
    setLoadingProfiles(true)
    setProfileError(null)
    try {
      const result = await api.clusterProfiles({
        namespace,
        epp_deployment: eppDeployment,
        epp_container: eppContainer,
      })
      setClusterInfo(result)
      setProfileInfos(result.profiles)
    } catch (cause) {
      setProfileError(String(cause))
    } finally {
      setLoadingProfiles(false)
    }
  }

  const visibleProfiles = useMemo(() => {
    const needle = profileSearch.trim().toLowerCase()
    const filtered = needle
      ? profileInfos.filter(
          (profile) =>
            profile.name.toLowerCase().includes(needle) ||
            profile.scorers.some((scorer) => scorer.type.toLowerCase().includes(needle)),
        )
      : profileInfos
    // Keep the source order, but list the no-header "default" entry last.
    return [...filtered].sort(
      (a, b) => (a.name === 'default' ? 1 : 0) - (b.name === 'default' ? 1 : 0),
    )
  }, [profileInfos, profileSearch])

  const toggleProfile = (profileName: string) => {
    setSelectedProfiles((previous) => {
      const next = new Set(previous)
      if (next.has(profileName)) next.delete(profileName)
      else next.add(profileName)
      return next
    })
  }

  const updateLoad = (index: number, patch: Partial<Load>) => {
    setLoads((previous) =>
      previous.map((load, i) => (i === index ? { ...load, ...patch } : load)),
    )
  }

  const buildParams = () => {
    const params: Record<string, unknown> = {
      endpoint,
      model,
      url,
      namespace,
      epp_deployment: eppDeployment,
      epp_container: eppContainer,
      profiles: Array.from(selectedProfiles),
      runs: loads.filter((load) => load.iterations >= 1 && load.concurrency >= 1),
      epp_scores: eppScores,
      no_backend_lookup: noBackendLookup,
      gateway_wait: gatewayWait,
      epp_wait: eppWait,
      timeout: timeoutSeconds,
    }
    if (endpoint === '/v1/chat/completions') {
      params.tokenizer = tokenizer
      params.modalities = modalities
    }
    if (voice.trim()) params.voice = voice.trim()
    if (audioFormat.trim()) params.audio_format = audioFormat.trim()
    if (sessionLength >= 2) {
      params.session_length = sessionLength
      params.session_header = sessionHeader
    }
    if (apiKey.trim()) params.api_key = apiKey.trim()
    if (promptMode === 'multi' && promptsText.trim()) params.prompts_text = promptsText
    else if (prompt.trim()) params.prompt = prompt
    return params
  }

  const validate = (): string | null => {
    if (!selectedProfiles.size) return 'Select at least one profile.'
    if (!loads.length || loads.some((load) => load.iterations < 1 || load.concurrency < 1)) {
      return 'Every load setting needs iterations and concurrency of at least 1.'
    }
    if (endpoint === '/v1/chat/completions' && !tokenizer.trim()) {
      return 'A tokenizer is required for /v1/chat/completions runs.'
    }
    if (sessionLength === 1) return 'Session length must be 0 (off) or at least 2.'
    return null
  }

  const doPreview = async () => {
    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(null)
    try {
      const result = await api.previewRun({ name: name || null, params: buildParams() })
      setPreview(result.profiles.map((p) => p.argv.join(' \\\n    ')))
    } catch (cause) {
      setError(String(cause))
    } finally {
      setBusy(false)
    }
  }

  const start = async () => {
    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(null)
    try {
      const result = await api.createRun({ name: name || null, params: buildParams() })
      navigate(`/runs/${result.id}`)
    } catch (cause) {
      setError(String(cause))
      setBusy(false)
    }
  }

  const isChat = endpoint === '/v1/chat/completions'

  return (
    <div>
      <div className="page-head">
        <h1>New benchmark run</h1>
      </div>
      {error && <div className="error-text panel">{error}</div>}

      <div className="panel">
        <h2>Basics</h2>
        <div className="form-grid">
          <div>
            <label>
              Run name (optional)
              <HelpHint text="A label for this run in History. If left empty, the selected profile names are used." />
            </label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)}
              placeholder="e.g. tts load combos repeat 1" />
          </div>
          <div>
            <label>
              Endpoint
              <HelpHint text="Which API to test. /v1/audio/speech sends text-to-speech requests. /v1/chat/completions sends chat requests and needs a tokenizer for token counting." />
            </label>
            <select value={endpoint} onChange={(e) => setEndpoint(e.target.value as typeof endpoint)}>
              <option value="/v1/audio/speech">/v1/audio/speech (TTS)</option>
              <option value="/v1/chat/completions">/v1/chat/completions (chat)</option>
            </select>
          </div>
          <div>
            <label>
              Model
              <HelpHint text="Model name sent in each API request. Must match a model the Gateway serves (e.g. qwen3-tts)." />
            </label>
            <input type="text" value={model} onChange={(e) => setModel(e.target.value)} />
          </div>
          <div>
            <label>
              Gateway URL
              <HelpHint text="Address of the inference Gateway. Requests go straight to it — no cluster login is needed for the latency measurements." />
            </label>
            <input type="text" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <div>
            <label>
              Namespace
              <HelpHint text="Cluster namespace for the read-only oc lookups: pod names, Gateway logs, EPP config. Needs a valid oc login; without it, latency still works but routing shows 'unknown'." />
            </label>
            <input type="text" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>Profiles</h2>
        <p className="muted">
          Built-in list comes from the script's PROFILE_SCORERS map. "Load from cluster"
          reads the live EPP ConfigMap instead (read-only <code>oc get</code>), which also
          shows combined profiles and weights that are not in the built-in map.
        </p>
        <div className="form-grid">
          <div>
            <label>Filter</label>
            <input type="text" value={profileSearch} placeholder="name or scorer type…"
              onChange={(e) => setProfileSearch(e.target.value)} />
          </div>
          <div>
            <label>
              EPP deployment / container (cluster lookup)
              <HelpHint text="Where to read the live EPP plugin ConfigMap from when using 'Load from cluster'. Read-only oc get; nothing on the cluster is changed." />
            </label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input type="text" value={eppDeployment} onChange={(e) => setEppDeployment(e.target.value)} />
              <input type="text" value={eppContainer} onChange={(e) => setEppContainer(e.target.value)} />
            </div>
          </div>
          <div style={{ alignSelf: 'end' }}>
            <button onClick={loadFromCluster} disabled={loadingProfiles}>
              {loadingProfiles ? 'Loading…' : 'Load from cluster'}
            </button>
          </div>
        </div>
        {clusterInfo && (
          <p className="muted">
            Cluster source: ConfigMap <code>{clusterInfo.configmap}</code> key{' '}
            <code>{clusterInfo.config_key}</code>
            {clusterInfo.api_version ? <> · apiVersion <code>{clusterInfo.api_version}</code></> : null}
            {clusterInfo.api_version?.includes('v1alpha1') && (
              <span className="warn-text"> (v1alpha1 is deprecated upstream)</span>
            )}
          </p>
        )}
        {profileError && <div className="error-text">{profileError}</div>}
        <div className="profile-list">
          {visibleProfiles.map((profile) => (
            <label key={profile.name} className="profile-item">
              <input
                type="checkbox"
                checked={selectedProfiles.has(profile.name)}
                onChange={() => toggleProfile(profile.name)}
              />
              <span className={`mono${profile.name === 'default' ? ' muted' : ''}`}>
                {profile.name}
              </span>
              <span className="muted profile-scorers">{profileSubText(profile)}</span>
            </label>
          ))}
          {!visibleProfiles.length && <div className="muted">No profiles match.</div>}
        </div>
        <p className="muted">Selected: {Array.from(selectedProfiles).join(', ') || '—'}</p>
      </div>

      <div className="panel">
        <h2>Load settings</h2>
        <p className="muted">
          Each selected profile runs once per load setting (like repeating{' '}
          <code>--run NxC</code>). Profiles run sequentially; requests within a run use the
          stated concurrency.
        </p>
        {loads.map((load, index) => (
          <div key={index} className="load-row">
            <label>
              Requests
              <HelpHint text="Total requests sent in the run (the N in --run NxC)." />
            </label>
            <input type="number" min={1} value={load.iterations}
              onChange={(e) => updateLoad(index, { iterations: Number(e.target.value) })} />
            <label>
              Concurrency
              <HelpHint text="Maximum requests kept in flight at the same time (the C in --run NxC)." />
            </label>
            <input type="number" min={1} value={load.concurrency}
              onChange={(e) => updateLoad(index, { concurrency: Number(e.target.value) })} />
            <button disabled={loads.length === 1} onClick={() => setLoads(loads.filter((_, i) => i !== index))}>
              remove
            </button>
          </div>
        ))}
        <button onClick={() => setLoads([...loads, { iterations: 50, concurrency: 10 }])}>
          add load setting
        </button>
      </div>

      <div className="panel">
        <h2>Input</h2>
        <div className="form-grid">
          <div>
            <label>
              Prompt mode
              <HelpHint text="Single prompt: the same input is sent for every request. Multiple prompts: one prompt per nonempty line, cycled through per request." />
            </label>
            <select value={promptMode} onChange={(e) => setPromptMode(e.target.value as 'single' | 'multi')}>
              <option value="single">Single prompt</option>
              <option value="multi">Multiple prompts (one per line)</option>
            </select>
          </div>
          {isChat && (
            <>
              <div>
                <label>
                  Modalities
                  <HelpHint text="Output types requested from chat completions: text, audio, or both." />
                </label>
                <select value={modalities} onChange={(e) => setModalities(e.target.value)}>
                  <option value="text,audio">text,audio</option>
                  <option value="text">text</option>
                  <option value="audio">audio</option>
                </select>
              </div>
              <div>
                <label>
                  Tokenizer (required)
                  <HelpHint text="Tokenizer used to count generated tokens for the TPOT estimate. Use the model's own tokenizer, e.g. Qwen/Qwen3-Omni-30B-A3B-Instruct." />
                </label>
                <input type="text" value={tokenizer} onChange={(e) => setTokenizer(e.target.value)}
                  placeholder="Qwen/Qwen3-Omni-30B-A3B-Instruct" />
              </div>
            </>
          )}
          <div>
            <label>
              Voice (optional)
              <HelpHint text="Voice for generated audio, e.g. vivian." />
            </label>
            <input type="text" value={voice} onChange={(e) => setVoice(e.target.value)} placeholder="vivian" />
          </div>
          <div>
            <label>
              Audio format (optional)
              <HelpHint text="Format of the generated audio, e.g. pcm." />
            </label>
            <input type="text" value={audioFormat} onChange={(e) => setAudioFormat(e.target.value)} placeholder="pcm" />
          </div>
        </div>
        {promptMode === 'single' ? (
          <div style={{ marginTop: 12 }}>
            <label>
              Prompt
              <HelpHint text="Sent as the input of every request." />
            </label>
            <input type="text" style={{ width: '100%' }} value={prompt} onChange={(e) => setPrompt(e.target.value)}
              placeholder="Say hello and introduce yourself in one sentence." />
          </div>
        ) : (
          <div style={{ marginTop: 12 }}>
            <label>
              Prompts
              <HelpHint text="One prompt per nonempty line; requests cycle through them in order. Mixing short and long inputs helps exercise load-based scorers." />
            </label>
            <textarea rows={6} value={promptsText} onChange={(e) => setPromptsText(e.target.value)}
              placeholder={'Hello. Your report is ready.\nGood morning, welcome to the briefing.'} />
          </div>
        )}
      </div>

      <div className="panel">
        <h2>Options</h2>
        <div className="form-grid">
          <div>
            <label>
              Session length (0 = off)
              <HelpHint text="Groups requests into conversations of up to this many sequential requests and replays each conversation's token. 0 = independent requests. Needed to exercise session affinity." />
            </label>
            <input type="number" min={0} value={sessionLength}
              onChange={(e) => setSessionLength(Number(e.target.value))} />
          </div>
          <div>
            <label>
              Session header
              <HelpHint text="HTTP header used to send and receive the session token (default: x-session-token)." />
            </label>
            <input type="text" value={sessionHeader} disabled={sessionLength < 2}
              onChange={(e) => setSessionHeader(e.target.value)} />
          </div>
          <div>
            <label>
              Gateway log wait (s)
              <HelpHint text="Seconds to wait for Gateway access logs when matching requests to backend pods. Increase it if routing often shows 'unknown'." />
            </label>
            <input type="number" min={0} value={gatewayWait}
              onChange={(e) => setGatewayWait(Number(e.target.value))} />
          </div>
          <div>
            <label>
              EPP score wait (s)
              <HelpHint text="Extra seconds to wait for missing EPP score records after the requests finish." />
            </label>
            <input type="number" min={0} value={eppWait}
              onChange={(e) => setEppWait(Number(e.target.value))} />
          </div>
          <div>
            <label>
              Request timeout (s)
              <HelpHint text="Per-request socket timeout. Requests that exceed it are recorded as failed." />
            </label>
            <input type="number" min={1} value={timeoutSeconds}
              onChange={(e) => setTimeoutSeconds(Number(e.target.value))} />
          </div>
          <div>
            <label>
              API key (optional)
              <HelpHint text="Bearer token sent to the Gateway if it requires authentication." />
            </label>
            <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          </div>
        </div>
        <div className="check-grid">
          <label className="check">
            <input type="checkbox" checked={eppScores} onChange={(e) => setEppScores(e.target.checked)} />
            Collect EPP scores
            <HelpHint text="Record per-request raw scorer scores, weighted contributions, and the picker's choice. Requires EPP running with --v=4 and JSON logging (--zap-encoder json)." />
          </label>
          <label className="check">
            <input type="checkbox" checked={noBackendLookup} onChange={(e) => setNoBackendLookup(e.target.checked)} />
            Skip pod/Gateway backend lookup
            <HelpHint text="Skip the oc queries that resolve which pod served each request. Latency metrics still work; routing will show 'unknown'." />
          </label>
        </div>
      </div>

      <div className="panel">
        <div className="actions">
          <button onClick={doPreview} disabled={busy}>Show command</button>
          <button className="primary" onClick={start} disabled={busy}>Start run</button>
        </div>
        {preview && (
          <div>
            <h2>Command preview</h2>
            {preview.map((argv, index) => (
              <pre key={index} className="log">{argv}</pre>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
