import React, { useEffect, useRef, useState } from 'react'
import QuickLog from './QuickLog.jsx'
import Switcher from './Switcher.jsx'
import Sheet from './Sheet.jsx'
import { fmtDate, fmtTime } from '../api.js'
import { headerLine, avatarOf } from '../personas.js'

// Header. Desktop: the person pill (opens the switcher), the wordmark, the tabs, then the sensor
// dot, the clock (time large, date gray) and "+ Log something". Phone: one row, avatar-only pill,
// sensor dot, time, a round "+" (the tabs move under the header).
export default function Header({ profile, profiles, home, health, onSwitch, onCreated, onAdd, onQuick, parser, tab, setTab, tabs, mobile }) {
  const [open, setOpen] = useState(false)       // quick-log
  const [who, setWho] = useState(false)         // switcher
  const [tip, setTip] = useState(false)         // sensor explanation (tap on phones)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const k = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', h); document.addEventListener('keydown', k)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k) }
  }, [open])
  const stale = home?.sensor?.staleness_min
  const tone = stale == null ? 'off' : stale <= 10 ? 'good' : stale <= 20 ? 'warn' : 'bad'
  const word = stale == null ? 'checking sensor' : stale <= 10 ? 'sensor fresh' : stale <= 20 ? 'sensor getting stale' : 'no sensor data'
  const tipText = stale == null ? 'Waiting for the sensor status.' : `Last glucose reading ${Math.round(stale)} min ago. Green: under 10 min. Amber: 10–20 min. Red: older than 20 min, when the app stops giving advice.`
  const quick = <QuickLog parser={parser} onAction={(a) => { setOpen(false); onQuick(a) }} />
  return (
    <header className={`header ${mobile ? 'mobile' : ''}`} ref={ref}>
      <button type="button" className={`who-pill ${who ? 'open' : ''}`} onClick={() => setWho((w) => !w)} aria-haspopup="dialog" aria-expanded={who} data-testid="who-pill" title="Switch person">
        <span className="avatar emoji">{avatarOf(profile)}</span>
        {!mobile ? <span className="lines"><b>{profile.name}</b><small>{headerLine(profile)}</small></span> : null}
        {!mobile ? <span className="caret">▾</span> : null}
      </button>
      {who ? <Switcher profiles={profiles} current={profile} mobile={mobile} onClose={() => setWho(false)} onSelect={onSwitch} onCreated={onCreated} onAdd={onAdd} /> : null}
      {!mobile ? <span className="brand">Gluco<span>Pilot</span></span> : null}
      {!mobile ? <nav className="tabs">{tabs.map((t) => <button key={t} type="button" className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}</nav> : null}
      <div className="spacer" />
      <button type="button" className="sensor" onClick={() => setTip((t) => !t)} title={tipText} aria-label={word} data-testid="sensor"><span className={`dot ${tone}`} />{!mobile ? word : null}</button>
      <span className="clock" data-testid="clock" title="The clock. The demo person's data is lined up with the real time, so the numbers move as time passes.">
        <b>{health?.wall_now ? fmtTime(health.wall_now) : ''}</b>
        {!mobile ? <small>{health?.wall_now ? fmtDate(health.wall_now) : ''}</small> : null}
      </span>
      {mobile
        ? <button type="button" className="primary round" onClick={() => setOpen((o) => !o)} aria-label="Log something" data-testid="log-button">+</button>
        : <button type="button" className="primary" onClick={() => setOpen((o) => !o)} data-testid="log-button">+ Log something</button>}
      {open && !mobile ? <div className="popover">{quick}</div> : null}
      {open && mobile ? <Sheet title="Log something" onClose={() => setOpen(false)} testId="log-sheet">{quick}</Sheet> : null}
      {tip ? <div className="sensor-tip" onClick={() => setTip(false)}>{tipText}</div> : null}
    </header>
  )
}
