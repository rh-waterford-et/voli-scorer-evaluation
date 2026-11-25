export interface Box {
  left: number
  right: number
  top: number
  bottom: number
  width: number
  height: number
}

// Place below when possible, otherwise above; clamp both axes to the viewport.
export function hintPosition(anchor: Box, popup: Box, viewportWidth: number, viewportHeight: number) {
  const margin = 8
  const gap = 5
  const maxLeft = Math.max(margin, viewportWidth - popup.width - margin)
  const left = Math.min(maxLeft, Math.max(margin, anchor.left + anchor.width / 2 - popup.width / 2))
  const below = anchor.bottom + gap
  const above = anchor.top - gap - popup.height
  const preferredTop = below + popup.height <= viewportHeight - margin ? below : above
  const maxTop = Math.max(margin, viewportHeight - popup.height - margin)
  const top = Math.min(maxTop, Math.max(margin, preferredTop))
  return { left, top }
}
