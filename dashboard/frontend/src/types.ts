// Shapes returned by the dashboard backend (dashboard/backend/*.py).

export interface MetricSummary {
  n: number | null
  mean: number | null
  p50: number | null
  p99: number | null
}

export interface EppScoreCell {
  type?: string | null
  raw: number | null
  weight?: number | null
  weighted?: number | null
}

export interface EppScoreCandidate {
  endpoint_id: string
  pod: string | null
  selected: boolean | null
  weighted_total: number | null
  computed_total?: number | null
  scores: Record<string, EppScoreCell>
}

export interface EppScoreDecision {
  epp_pod: string
  request_id: string
  endpoints: EppScoreCandidate[]
  issues: string[]
}

export interface EppScoreRecord {
  status: string
  decisions: EppScoreDecision[]
}

export interface EppScoreSummary {
  profile: string
  coverage: Record<string, number>
  uncorrelated_records?: number
  warnings?: string[]
}

export interface SessionReplay {
  header: string
  session_length: number
  sessions: number
  concurrent_sessions: number
  followup_requests: number
  replayed_requests: number
  followups_without_token: number
  responses_with_token: number
  same_pod: number
  changed_pod: number
  unresolved_pod: number
  latency: Record<string, Record<string, MetricSummary>>
}

export interface RequestResult {
  iteration: number
  status: string
  error?: string | null
  pod?: string | null
  upstream?: string | null
  http_status?: number | null
  e2e_ms?: number | null
  ttft_ms?: number | null
  ttfo_ms?: number | null
  ttfa_ms?: number | null
  text_chunks?: number | null
  audio_chunks?: number | null
  missing_modalities?: string[]
  profile: string
  scorer: string
  epp_scores?: EppScoreRecord
  session_id?: string
  session_turn?: number
  session_token_sent?: string | null
}

export interface ScriptRun {
  run_id: string
  profile: string
  scorer: string
  iterations: number
  concurrency: number
  duration_seconds: number
  valid_responses: number
  failed_responses: number
  missing_output_responses: number
  routing: Record<string, number>
  metrics: Record<string, MetricSummary>
  results?: RequestResult[]
  epp_scores?: EppScoreSummary
  session_replay?: SessionReplay
}

export interface ProfileAttempt {
  name: string
  status: string
  argv: string[]
  returncode: number | null
  result_file: string
  error: string | null
  index?: number
  total?: number
}

export interface RunSummary {
  profiles: string[]
  run_count: number
  requests: number
  valid: number
  failed: number
}

export interface RunParams {
  endpoint: string
  model: string
  url: string
  profiles: string[]
  runs: { iterations: number; concurrency: number }[]
  prompt?: string | null
  prompts_text?: string | null
  modalities?: string
  voice?: string | null
  audio_format?: string | null
  tokenizer?: string | null
  api_key?: string | null
  session_length?: number
  session_header?: string
  epp_scores?: boolean
  no_backend_lookup?: boolean
  no_usage?: boolean
  namespace?: string
  gateway_name?: string
  gateway_container?: string
  epp_deployment?: string
  epp_container?: string
  epp_configmap?: string | null
  epp_config_key?: string | null
  gateway_wait?: number
  epp_wait?: number
  timeout?: number
}

export interface ResultsDoc {
  model: string | null
  endpoint: string | null
  modalities: string[]
  runs: ScriptRun[]
}

export interface RunMeta {
  id: string
  name: string | null
  created_at: string | null
  status: string
  source: string
  summary?: RunSummary
  model?: string | null
  endpoint?: string | null
}

export interface RunDetail extends RunMeta {
  params?: RunParams
  profiles?: ProfileAttempt[]
  results?: ResultsDoc
  error?: string | null
  finished_at?: string
}

export interface PluginRef {
  name: string | null
  type: string
  weight: number | null
}

export interface ProfileInfo {
  name: string
  source: string
  scorers: PluginRef[]
  filters: PluginRef[]
  pickers: PluginRef[]
}

export interface ClusterProfiles {
  namespace: string
  epp_deployment: string
  configmap: string
  config_key: string
  resource_version?: string | null
  api_version?: string | null
  profiles: ProfileInfo[]
}

export interface ProfileListResponse {
  source: string
  map_source: 'local' | 'default'
  map_synced_at: string | null
  map_sync_source: string | null
  map_profiles: number | null
  profiles: ProfileInfo[]
}

// -- scorer caveats / operability --------------------------------------------------

export type CheckSeverity = 'ok' | 'warn' | 'bad' | 'unknown'

export interface ProfileCheck {
  severity: CheckSeverity
  status: string
  statuses: string[]
  reasons: string[]
  scorer_types: string[]
}

export interface ScorerCheck {
  severity: CheckSeverity
  reasons: string[]
}

export interface ProfilesCheckResponse {
  verified_as_of: string | null
  cluster_access: 'ok' | 'unavailable'
  cluster_error: string | null
  endpoint: string
  profiles: Record<string, ProfileCheck>
  scorers: Record<string, ScorerCheck>
}

export interface RunEvent {
  kind: string
  data: any
}

// -- profile builder ------------------------------------------------------------

export interface BuilderInstance {
  name: string
  type: string
  kind: 'scorer' | 'picker' | 'other'
  has_parameters: boolean
}

export interface BuilderScorerRef {
  name: string
  weight: number | null
}

export interface BuilderProfile {
  name: string
  scorers: BuilderScorerRef[]
  others: BuilderScorerRef[]
  picker: string | null
}

export interface BuilderState {
  namespace: string
  epp_deployment: string
  configmap: string
  config_key: string
  resource_version: string | null
  api_version: string
  default_profile: string | null
  helm_managed: boolean
  picker_default: string | null
  instances: BuilderInstance[]
  profiles: BuilderProfile[]
  warnings: string[]
}

export interface BuilderOperationIn {
  action: 'create' | 'edit' | 'delete'
  profile: string
  scorers: { name: string; weight: number }[]
  picker?: string | null
}

export interface BuilderPreview {
  ok: boolean
  errors: string[]
  warnings: string[]
  resource_version: string | null
  diff: string
  new_text: string
  picker: string | null
  configmap: string
  config_key: string
  summary: string
}

export interface BuilderJobStep {
  key: string
  label: string
  status: string
  detail: string | null
}

export interface BuilderJob {
  id: string
  kind: 'apply' | 'revert'
  status: string
  error: string | null
  summary: string
  created_at: string
  steps: BuilderJobStep[]
  backup_id: string | null
  revert_available: boolean
}

export interface BuilderBackup {
  id: string
  created_at: string
  namespace: string
  epp_deployment: string
  configmap: string
  config_key: string
  resource_version: string | null
  operation: string
}
