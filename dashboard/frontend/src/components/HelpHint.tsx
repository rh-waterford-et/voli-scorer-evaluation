import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from 'react'

// Only one hint may be open at a time; opening one closes the others.
const CLOSE_EVENT = 'voli-help-hint-close'
const VIEWPORT_MARGIN = 8

export default function HelpHint({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLSpanElement>(null)
  const popupRef = useRef<HTMLSpanElement>(null)

  // The popup is centered under the ? by default (CSS transform). When that
  // would push it past the left or right window edge, shift it sideways just
  // enough to stay inside the viewport. Runs before paint, so no flicker;
  // re-runs on window resize while open.
  useLayoutEffect(() => {
    if (!open) return
    const popup = popupRef.current
    if (!popup) return
    const clamp = () => {
      popup.style.transform = 'translateX(-50%)'
      const rect = popup.getBoundingClientRect()
      if (!rect.width) return
      const leftLimit = VIEWPORT_MARGIN
      const rightLimit = window.innerWidth - VIEWPORT_MARGIN
      let delta = 0
      if (rect.left < leftLimit) delta = leftLimit - rect.left
      else if (rect.right > rightLimit) delta = rightLimit - rect.right
      if (delta !== 0) {
        popup.style.transform = `translateX(calc(-50% + ${delta}px))`
      }
    }
    clamp()
    window.addEventListener('resize', clamp)
    return () => window.removeEventListener('resize', clamp)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: Event) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onCloseAll = () => setOpen(false)
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener(CLOSE_EVENT, onCloseAll)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener(CLOSE_EVENT, onCloseAll)
    }
  }, [open])

  const toggle = (event: ReactMouseEvent<HTMLButtonElement>) => {
    // Inside <label>: prevent the label from focusing/toggling the input.
    event.preventDefault()
    event.stopPropagation()
    if (!open) window.dispatchEvent(new Event(CLOSE_EVENT))
    setOpen(!open)
  }

  return (
    <span className="hint-wrap" ref={rootRef}>
      <button
        type="button"
        className="hint-button"
        aria-label="What is this?"
        aria-expanded={open}
        onClick={toggle}
      >
        ?
      </button>
      {open && (
        <span className="hint-popup" role="tooltip" ref={popupRef}>
          {text}
        </span>
      )}
    </span>
  )
}
