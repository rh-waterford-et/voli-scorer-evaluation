import type { RunDetail } from './types'

export function isTranscription(detail: RunDetail): boolean {
  return detail.params?.endpoint === '/v1/audio/transcriptions' ||
    (detail.results?.endpoint ?? '').includes('/v1/audio/transcriptions')
}

export function promptOf(detail: RunDetail): string | null {
  if (detail.params) {
    const text = (detail.params.prompts_text ?? '').trim()
    if (text) return text
    return (detail.params.prompt ?? '').trim() || (isTranscription(detail) ? '(no hint)' : '(script default)')
  }
  if (isTranscription(detail) && Array.isArray(detail.results?.transcription_hints)) {
    return detail.results.transcription_hints.join('\n').trim() || '(no hint)'
  }
  return null
}
