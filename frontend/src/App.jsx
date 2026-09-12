import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, pct } from './api.js'
import NowTab from './components/NowTab.jsx'
import TodayTab from './components/TodayTab.jsx'
import BodyTab from './components/BodyTab.jsx'
import TrendsTab from './components/TrendsTab.jsx'
import ReplayTab from './components/ReplayTab.jsx'
import Chat from './components/Chat.jsx'

const TABS = ['Now', 'Today', 'Body', 'Trends', 'Replay']

export default function App() {
  const [tab, setTab] = useState('Now')
  const [health, setHealth] = useState(null)
  const [state, setState] = useState(null)
  const [drift, setDrift] = useState(null)
  const [parser, setParser] = useState(null)
  const [cards, setCards] = useState([])          // permission / change cards shown in Today
  const [pendingChange, setPendingChange] = useState(null)
  const [planned, setPlanned] = useState([])
  const [forecastKey, setForecastKey] = useState(0)  // bump to refetch forecasts after accepting events
  const [error, setError] = useState(null)

  const refreshHeader = useCallback(async () => {
    try {
      const [h, s, d, p] = await Promise.all([api.health(), api.state(), api.drift(), api.parserStatus()])
      setHealth(h); setState(s); setDrift(d); setParser(p)
    } catch (e) { setError(String(e.message || e)) }
  }, [])

  useEffect(() => { refreshHeader() }, [refreshHeader])

  const onCard = useCallback((card) => {
    setCards((c) => [{ ...card, at: Date.now() }, ...c])
    if (card.kind === 'change') setPendingChange(card.payload)
  }, [])

  const onAccepted = useCallback(async () => {
    try { setPlanned(await api.planned()) } catch (e) { /* ignore */ }
    setForecastKey((k) => k + 1)
  }, [])

  const onParser = useCallback((name) => setParser((p) => ({ ...(p || {}), last_parser: name })), [])

  const sync = drift ? (drift.flagged ? (drift.days_flagged >= 5 ? 'red' : 'amber') : 'green') : 'gray'
  const q = state ? state.data_quality : null
  const qColor = q == null ? 'gray' : q >= 0.7 ? 'green' : q >= 0.4 ? 'amber' : 'red'

  return (
    <div className="app">
      <header className="header">
        <div className="brand">Gluco<span>Pilot</span></div>
        <span className="pill"><span className={`dot ${sync}`} /> Twin sync {drift ? <b>{drift.flagged ? `drift x${drift.score}` : `ok (x${drift.score})`}</b> : '…'}</span>
        <span className="pill"><span className={`dot ${qColor}`} /> Data quality {q != null ? <b>{q.toFixed(2)}</b> : '…'}</span>
        <span className="pill">CGM {state ? <b>{state.staleness_min.toFixed(0)} min old</b> : '…'}</span>
        <span className="pill">Parser: <b className={parser?.last_parser === 'gemini' ? 'ok' : ''}>{parser ? (parser.last_parser === 'gemini' ? 'Gemini' : 'local fallback') : '…'}</b>{parser && !parser.gemini_configured ? <span className="muted"> (no key)</span> : null}</span>
        <div className="spacer" />
        <span className="pill">Twin clock <b>{health ? health.now.replace('T', ' ') : '…'}</b></span>
        <Link to="/clinician" className="pill">Clinician view</Link>
      </header>
      <div className="main">
        <div className="left">
          <nav className="tabs">
            {TABS.map((t) => <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}
          </nav>
          <div className="content">
            {error ? <div className="err">Backend error: {error}. Is the API running on port 8000?</div> : null}
            {tab === 'Now' ? <NowTab state={state} forecastKey={forecastKey} /> : null}
            {tab === 'Today' ? <TodayTab cards={cards} planned={planned} forecastKey={forecastKey} onAccepted={onAccepted} /> : null}
            {tab === 'Body' ? <BodyTab state={state} pendingChange={pendingChange} /> : null}
            {tab === 'Trends' ? <TrendsTab /> : null}
            {tab === 'Replay' ? <ReplayTab /> : null}
          </div>
        </div>
        <aside className="right">
          <Chat onCard={onCard} onAccepted={onAccepted} onParser={onParser} onChange={(c) => setPendingChange(c)} goTo={setTab} />
        </aside>
      </div>
    </div>
  )
}
