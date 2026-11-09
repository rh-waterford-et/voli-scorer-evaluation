import type { RunDetail } from './types'

export function isTranscription(detail: RunDetail): boolean {
  return detail.params?.endpoint === '/v1/audio/transcriptions' ||
    (detail.results?.endpoint ?? '').includes('/v1/audio/transcriptions')
}

export function transcriptionModeState(details: RunDetail[]): { mismatch: boolean; unknown: boolean } {
  const modes = details.filter(isTranscription).map((detail) =>
    detail.results?.transcription_stream ?? detail.params?.transcription_stream ?? null,
  )
  return {
    mismatch: modes.includes(true) && modes.includes(false),
    unknown: modes.includes(null),
  }
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
