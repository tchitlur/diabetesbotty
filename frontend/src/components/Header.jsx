import React, { useEffect, useRef, useState } from 'react'
import QuickLog from './QuickLog.jsx'
import { fmtDate, fmtTime } from '../api.js'

// Header: profile switcher, app name, tabs, sensor-status dot (plain tooltip), "Log something".
export default function Header({ profile, profiles, home, health, onSwitch, onLogout, onQuick, parser, tab, setTab, tabs }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const k = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', h)
    document.addEventListener('keydown', k)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k) }
  }, [open])
  const stale = home?.sensor?.staleness_min
  const tone = stale == null ? 'off' : stale <= 10 ? 'good' : stale <= 20 ? 'warn' : 'bad'
  const word = stale == null ? 'checking sensor' : stale <= 10 ? 'sensor fresh' : stale <= 20 ? 'sensor getting stale' : 'no sensor data'
  const tip = stale == null ? 'Waiting for the sensor status.' : `Last glucose reading ${Math.round(stale)} min ago. Green: under 10 min. Amber: 10–20 min. Red: older than 20 min, when the app stops giving advice.`
  return (
    <header className="header" ref={ref}>
      <span className="who">
        <span className="avatar">{profile.initial}</span>
        <select value={profile.id} onChange={(e) => (e.target.value === '__out' ? onLogout() : onSwitch(e.target.value))} aria-label="profile" title="Switch profile">
          {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          <option value="__out">Switch profile…</option>
        </select>
      </span>
      <span className="brand">Gluco<span>Pilot</span></span>
      <nav className="tabs">{tabs.map((t) => <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}</nav>
      <div className="spacer" />
      <span className="sensor" title={tip}><span className={`dot ${tone}`} />{word}</span>
      <span className="sensor" data-testid="clock" title="The clock. The demo person's data is lined up with the real time, so the numbers move as time passes.">{health?.wall_now ? `${fmtDate(health.wall_now)} · ${fmtTime(health.wall_now)}` : ''}</span>
      <button className="primary" onClick={() => setOpen((o) => !o)}>Log something</button>
      {open ? <div className="popover"><QuickLog parser={parser} onAction={(a) => { setOpen(false); onQuick(a) }} /></div> : null}
    </header>
  )
}
