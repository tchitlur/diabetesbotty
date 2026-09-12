import React, { useEffect, useRef, useState } from 'react'
import { useVisualViewportHeight } from '../hooks.js'

// A bottom sheet for phones: slides up, closes on the backdrop, the ✕, Escape, or a downward drag
// on the handle. `full` makes it a full-screen sheet whose height follows the visual viewport, so
// the input at its bottom stays above the on-screen keyboard.
export default function Sheet({ title, onClose, children, full = false, testId = 'sheet', hideHead = false }) {
  const vh = useVisualViewportHeight()
  const [drag, setDrag] = useState(null)
  const [dy, setDy] = useState(0)
  const ref = useRef(null)
  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', k)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.removeEventListener('keydown', k); document.body.style.overflow = prev }
  }, [onClose])
  const onDown = (e) => { setDrag(e.clientY); e.currentTarget.setPointerCapture?.(e.pointerId) }
  const onMove = (e) => { if (drag != null) setDy(Math.max(0, e.clientY - drag)) }
  const onUp = () => { if (drag != null && dy > 80) onClose(); setDrag(null); setDy(0) }
  const style = full ? { height: vh ? `${vh}px` : '100dvh', top: `calc(${window.visualViewport?.offsetTop || 0}px)` } : {}
  return (
    <div className="sheet-backdrop" onClick={onClose} data-testid={`${testId}-backdrop`}>
      <div ref={ref} className={`sheet ${full ? 'full' : ''}`} role="dialog" aria-label={title || 'sheet'} data-testid={testId} style={{ ...style, transform: dy ? `translateY(${dy}px)` : undefined }} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}><i /></div>
        {hideHead ? null : <div className="sheet-head">
          <b>{title}</b>
          <button type="button" className="icon" aria-label="close" onClick={onClose} data-testid={`${testId}-close`}>✕</button>
        </div>}
        <div className="sheet-body">{children}</div>
      </div>
    </div>
  )
}
