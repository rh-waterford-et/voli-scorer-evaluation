// Browser-local draft persistence for form state that should survive view
// switches and page reloads. localStorage is per-browser and never leaves the
// machine; anything sensitive (API keys, uploaded files) is deliberately not
// persisted. All functions fail silently: a broken or unreadable draft must
// never break the form — it just falls back to empty (placeholder) values.

const PREFIX = 'voli:'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function loadDraft<T = any>(key: string): Partial<T> | null {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

export function saveDraft(key: string, value: unknown): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    /* storage full or unavailable — drafts are best-effort */
  }
}

export function clearDraft(key: string): void {
  try {
    localStorage.removeItem(PREFIX + key)
  } catch {
    /* ignore */
  }
}
