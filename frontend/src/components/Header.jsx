import React from 'react'
import { Link } from 'react-router-dom'
import { pct } from '../api.js'

// Shared header for the dashboard and the clinician page. Every indicator has a
// plain-language label and a title attribute that explains it on hover.
export default function Header({ health, state, drift, parser, right }) {
  const syncTone = drift ? (drift.days_flagged >= 5 ? 'bad' : drift.flagged ? 'warn' : 'good') : 'off'
  const syncText = drift ? (drift.days_flagged >= 5 ? 'escalate' : drift.flagged ? 'drifting' : 'in sync') : 'checking…'
  const syncTitle = drift
    ? `Twin sync compares the twin's 60-minute forecast with the CGM every day. Drift score ${drift.score} = today's error relative to the recent median (1.0 = unchanged). ${drift.flagged ? `Rising for ${drift.days_flagged} day(s) since ${drift.since}.` : 'Not rising: the twin still matches the sensor.'}`
    : 'Loading drift status'
  const q = state ? state.data_quality : null
  const qTone = q == null ? 'off' : q >= 0.7 ? 'good' : q >= 0.4 ? 'warn' : 'bad'
  const qTitle = 'Data quality 0–100 %: CGM coverage over the last 24 h and overall, penalised for rate-of-change artifacts and stale readings. Decisions are refused below 30 %.'
  const stale = state ? Math.round(state.staleness_min) : null
  const pTitle = parser
    ? (parser.gemini_configured ? `Gemini (${parser.model}) parses text and photos into structured events; the local regex + food-table parser takes over if a call fails.` : 'No GEMINI_API_KEY configured: the deterministic local parser (regex + food table) is handling text. Run scripts\\setup_key.ps1 to enable Gemini.')
    : ''
  return (
    <header className="header">
      <Link to="/" className="brand">Gluco<span>Pilot</span></Link>
      <span className="pill" title={syncTitle}><span className={`dot ${syncTone}`} />Twin sync&nbsp;<b>{syncText}</b>{drift ? <span className="faint">&nbsp;·&nbsp;drift {Number(drift.score).toFixed(2)}</span> : null}</span>
      <span className="pill" title={qTitle}><span className={`dot ${qTone}`} />Data quality&nbsp;<b>{q != null ? pct(q) : '…'}</b></span>
      <span className="pill" title="Minutes since the last valid CGM reading. Decisions are refused after 20 minutes."><span className={`dot ${stale == null ? 'off' : stale <= 20 ? 'good' : 'bad'}`} />CGM&nbsp;<b>{stale != null ? `${stale} min ago` : '…'}</b></span>
      <span className="pill" title={pTitle}>Parser:&nbsp;<b>{parser ? (parser.last_parser === 'gemini' ? 'Gemini' : 'local fallback') : '…'}</b>{parser && !parser.gemini_configured ? <span className="faint">&nbsp;(no key)</span> : null}</span>
      <div className="spacer" />
      <span className="pill" title="The demo clock. The twin lives at this moment inside the synthetic data and never sees anything after it.">Twin clock&nbsp;<b>{health ? health.now.replace('T', ' ') : '…'}</b></span>
      {right}
    </header>
  )
}
