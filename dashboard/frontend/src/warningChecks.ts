import type { ProfilesCheckResponse } from './types'

// Local caveats appear immediately. A successful live check can refine them,
// but an older local response must never replace a newer live result.
export function startWarningChecks(options: {
  local: () => Promise<ProfilesCheckResponse>
  live?: () => Promise<ProfilesCheckResponse>
  onResult: (result: ProfilesCheckResponse) => void
  onLocalError: () => void
  onLocalDone: () => void
  onLiveStatus: (status: 'checking' | 'ok' | 'unavailable') => void
  delay?: number
}) {
  let cancelled = false
  let liveApplied = false
  options.local().then((result) => {
    if (!cancelled && !liveApplied) options.onResult(result)
  }).catch(() => {
    if (!cancelled && !liveApplied) options.onLocalError()
  }).finally(() => {
    if (!cancelled) options.onLocalDone()
  })

  let timer: ReturnType<typeof setTimeout> | undefined
  if (options.live) {
    options.onLiveStatus('checking')
    timer = setTimeout(() => {
      options.live!().then((result) => {
        if (cancelled) return
        if (result.cluster_access !== 'ok') {
          options.onLiveStatus('unavailable')
          return
        }
        liveApplied = true
        options.onResult(result)
        options.onLiveStatus('ok')
      }).catch(() => {
        if (!cancelled) options.onLiveStatus('unavailable')
      })
    }, options.delay ?? 400)
  }

  return () => {
    cancelled = true
    if (timer !== undefined) clearTimeout(timer)
  }
}
