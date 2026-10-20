import type {
  ClusterProfiles,
  ProfileInfo,
  RunDetail,
  RunMeta,
} from './types'

async function getJSON<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* keep status text */
    }
    throw new Error(detail)
  }
  return response.json()
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const parsed = await response.json()
      if (parsed?.detail) detail = typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail)
    } catch {
      /* keep status text */
    }
    throw new Error(detail)
  }
  return response.json()
}

export const api = {
  runs: () => getJSON<RunMeta[]>('/api/runs'),

  run: (id: string) => getJSON<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),

  log: async (id: string, tail = 400): Promise<string> => {
    const response = await fetch(`/api/runs/${encodeURIComponent(id)}/log?tail=${tail}`)
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
    return response.text()
  },

  cancel: async (id: string): Promise<void> => {
    const response = await fetch(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  },

  remove: async (id: string): Promise<void> => {
    const response = await fetch(`/api/runs/${encodeURIComponent(id)}`, { method: 'DELETE' })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.detail || `${response.status} ${response.statusText}`)
    }
  },

  createRun: (body: { name?: string | null; params: unknown }) =>
    postJSON<{ id: string }>('/api/runs', body),

  previewRun: (body: { name?: string | null; params: unknown }) =>
    postJSON<{ run_id: string; profiles: { name: string; argv: string[] }[] }>('/api/runs/preview', body),

  builtinProfiles: () => getJSON<{ source: string; profiles: ProfileInfo[] }>('/api/profiles'),

  clusterProfiles: (query: {
    namespace: string
    epp_deployment: string
    epp_container: string
  }) => {
    const params = new URLSearchParams({
      namespace: query.namespace,
      epp_deployment: query.epp_deployment,
      epp_container: query.epp_container,
    })
    return getJSON<ClusterProfiles>(`/api/profiles/cluster?${params.toString()}`)
  },
}

export function openRunEvents(
  id: string,
  handlers: { [event: string]: (data: any) => void },
  onDone: () => void,
): EventSource {
  const source = new EventSource(`/api/runs/${encodeURIComponent(id)}/events`)
  for (const [event, handler] of Object.entries(handlers)) {
    source.addEventListener(event, (raw) => {
      const message = raw as MessageEvent
      let data: any = null
      try {
        data = message.data ? JSON.parse(message.data) : null
      } catch {
        data = null
      }
      handler(data)
    })
  }
  source.addEventListener('done', () => {
    source.close()
    onDone()
  })
  return source
}
