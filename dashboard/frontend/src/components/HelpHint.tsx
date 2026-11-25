import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from 'react'
import { createPortal } from 'react-dom'
import { hintPosition } from '../hintPosition'

// Only one hint may be open at a time; opening one closes the others.
const CLOSE_EVENT = 'voli-help-hint-close'

export default function HelpHint({ text, details, label = '?' }: { text: string; details?: string[]; label?: string }) {
  const [open, setOpen] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const rootRef = useRef<HTMLSpanElement>(null)
  const popupRef = useRef<HTMLSpanElement>(null)

  // A portal avoids clipping by scrollable containers. Keep it anchored to the
  // button as the page or a nested container scrolls, and when Details grows.
  useLayoutEffect(() => {
    if (!open) return
    const popup = popupRef.current
    const anchor = rootRef.current
    if (!popup || !anchor) return
    const reposition = () => {
      const rect = anchor.getBoundingClientRect()
      const position = hintPosition(rect, popup.getBoundingClientRect(), window.innerWidth, window.innerHeight)
      popup.style.left = `${position.left}px`
      popup.style.top = `${position.top}px`
      popup.style.visibility = 'visible'
    }
    reposition()
    window.addEventListener('resize', reposition)
    window.addEventListener('scroll', reposition, true)
    const observer = new ResizeObserver(reposition)
    observer.observe(popup)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', reposition)
      window.removeEventListener('scroll', reposition, true)
    }
  }, [open, showDetails])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: Event) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node) &&
          !popupRef.current?.contains(event.target as Node)) {
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
    if (!open) setShowDetails(false)
    setOpen(!open)
  }

  return (
    <span className="hint-wrap" ref={rootRef}>
      <button
        type="button"
        className={label === '?' ? 'hint-button' : 'badge warn warning-button'}
        aria-label={label === '?' ? 'What is this?' : `Show scorer ${label.toLowerCase()}`}
        aria-haspopup={details?.length ? 'dialog' : undefined}
        aria-expanded={open}
        onClick={toggle}
      >
        {label}
      </button>
      {open && createPortal(
        <span className="hint-popup" role={details?.length ? 'dialog' : 'tooltip'} aria-label={details?.length ? 'Scorer warning' : undefined} ref={popupRef} onClick={(event) => { event.preventDefault(); event.stopPropagation() }}>
          <span className="warning-summary">{text}</span>
          {details && details.length > 0 && (
            <span className="warning-details">
              <button type="button" aria-expanded={showDetails} onClick={(event) => {
                event.preventDefault()
                event.stopPropagation()
                setShowDetails(!showDetails)
              }}>Details</button>
              {showDetails && details.map((item, i) => <span className="warning-detail" key={i}>{item}</span>)}
            </span>
          )}
        </span>,
        document.body,
      )}
    </span>
  )
}
