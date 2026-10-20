export const METRIC_LABELS: Record<string, string> = {
  ttft_ms: 'TTFT (first text)',
  ttfo_ms: 'TTFO (first visible text)',
  ttfa_ms: 'TTFA (first audio)',
  tpot_estimate_ms: 'TPOT estimate',
  text_gap_ms: 'Text chunk gap',
  audio_gap_ms: 'Audio chunk gap',
  e2e_ms: 'End-to-end',
}

export const METRIC_ORDER = [
  'ttft_ms',
  'ttfo_ms',
  'ttfa_ms',
  'tpot_estimate_ms',
  'text_gap_ms',
  'audio_gap_ms',
  'e2e_ms',
]

export function fmtMs(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return value >= 100 ? value.toFixed(0) : value.toFixed(1)
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

export function fmtInt(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return Math.round(value).toString()
}

export function fmtPercent(part: number, total: number): string {
  if (!total) return '—'
  return `${((part / total) * 100).toFixed(1)}%`
}

export function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 90) return `${seconds.toFixed(1)} s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes}m ${rest}s`
}

export function loadLabel(run: { iterations: number; concurrency: number }): string {
  return `${run.iterations}×${run.concurrency}`
}

export function isActive(status: string | undefined | null): boolean {
  return status === 'queued' || status === 'running'
}

export function statusClass(status: string | undefined | null): string {
  switch (status) {
    case 'completed':
      return 'badge ok'
    case 'running':
    case 'queued':
      return 'badge running'
    case 'failed':
      return 'badge bad'
    case 'cancelled':
    case 'interrupted':
    case 'skipped':
      return 'badge warn'
    default:
      return 'badge'
  }
}

export function shortPod(pod: string | null | undefined): string {
  if (!pod) return 'unknown'
  const parts = pod.split('/')
  const name = parts[parts.length - 1]
  return name.length > 34 ? `${name.slice(0, 16)}…${name.slice(-14)}` : name
}
