import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { describe, ratioLine, avatarOf } from '../personas.js'
import Sheet from './Sheet.jsx'

// "WHO IS ASKING?": the same people as the login screen, the current one highlighted, then
// "Random new person" and "Add someone". A card under the header pill on desktop, a bottom sheet on phones.
export default function Switcher({ profiles, current, onSelect, onAdd, onCreated, onClose, mobile }) {
  const [busy, setBusy] = useState(null)   // id being switched to, or 'random'
  const [err, setErr] = useState(null)
  const ref = useRef(null)
  useEffect(() => {
    if (mobile) return undefined
    const h = (e) => { if (ref.current && !ref.current.contains(e.target) && !e.target.closest('.who-pill')) onClose() }
    const k = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('mousedown', h); document.addEventListener('keydown', k)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k) }
  }, [onClose, mobile])
  const pick = async (id) => {
    if (busy) return
    if (id === current?.id) { onClose(); return }
    setBusy(id); setErr(null)
    try { await onSelect(id); onClose() } catch (e) { setErr(String(e.message)) } finally { setBusy(null) }
  }
  const random = async () => {
    if (busy) return
    setBusy('random'); setErr(null)
    try { const p = await api.randomProfile(); onCreated(p); onClose() } catch (e) { setErr(String(e.message)) } finally { setBusy(null) }
  }
  const body = (
    <div className="switcher" ref={ref} data-testid="switcher">
      {!mobile ? <div className="switcher-title">Who is asking?</div> : null}
      <div className="persona-list">
        {profiles.map((p) => (
          <button key={p.id} type="button" className={`persona-row ${p.id === current?.id ? 'current' : ''}`} onClick={() => pick(p.id)} disabled={!!busy} data-testid={`switch-${p.id}`}>
            <span className="avatar lg emoji">{avatarOf(p)}</span>
            <span className="lines">
              <b>{p.name}</b>
              {describe(p) ? <small>{describe(p)}</small> : null}
              <small>{ratioLine(p)}</small>
            </span>
            {busy === p.id ? <span className="spinner" /> : null}
          </button>
        ))}
        <button type="button" className="persona-row" onClick={random} disabled={!!busy} data-testid="switch-random">
          <span className="avatar lg emoji">🎲</span>
          <span className="lines"><b>Random new person</b><small>a new virtual patient with their own physiology, fitted on the spot (~10 s)</small></span>
          {busy === 'random' ? <span className="spinner" /> : null}
        </button>
        <button type="button" className="persona-row" onClick={() => { onClose(); onAdd() }} disabled={!!busy} data-testid="switch-add">
          <span className="avatar lg emoji">＋</span>
          <span className="lines"><b>Add someone</b><small>choose their details yourself</small></span>
        </button>
      </div>
      {err ? <div className="err">{err}</div> : null}
    </div>
  )
  if (mobile) return <Sheet title="Who is asking?" onClose={onClose} testId="switcher-sheet">{body}</Sheet>
  return body
}
