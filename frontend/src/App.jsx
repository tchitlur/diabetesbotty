import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from './api.js'
import Header from './components/Header.jsx'
import NowTab from './components/NowTab.jsx'
import TodayTab from './components/TodayTab.jsx'
import BodyTab from './components/BodyTab.jsx'
import TrendsTab from './components/TrendsTab.jsx'
import ReplayTab from './components/ReplayTab.jsx'
import Chat from './components/Chat.jsx'

const TABS = ['Now', 'Today', 'Body', 'Trends', 'Replay']

// A tiny resource holder: { data, loading, error }. All tab data is fetched here once
// (and prefetched at start) so switching tabs never shows a blank card.
const idle = { data: null, loading: false, error: null }

export default function App() {
  const [tab, setTab] = useState('Now')
  const [health, setHealth] = useState(null)
  const [state, setState] = useState(null)
  const [drift, setDrift] = useState(null)
  const [parser, setParser] = useState(null)
  const [cards, setCards] = useState([])
  const [pendingChange, setPendingChange] = useState(null)
  const [planned, setPlanned] = useState([])
  const [error, setError] = useState(null)
  const [forecast, setForecast] = useState(idle)
  const [history, setHistory] = useState(idle)
  const [plan, setPlan] = useState(idle)
  const [alerts, setAlerts] = useState(idle)
  const [baseline, setBaseline] = useState(idle)
  const [trends, setTrends] = useState(idle)

  const load = useCallback(async (setter, fn) => {
    setter((r) => ({ ...r, loading: true, error: null }))
    try { const data = await fn(); setter({ data, loading: false, error: null }) } catch (e) { setter({ data: null, loading: false, error: e.message || String(e) }) }
  }, [])

  const refreshForecast = useCallback(() => { load(setForecast, () => api.forecast(480)); load(setHistory, () => api.history(6)) }, [load])
  const refreshPlan = useCallback(() => { load(setPlan, () => api.plan(0)); load(setAlerts, () => api.alerts()) }, [load])

  useEffect(() => {
    (async () => {
      try {
        const [h, s, d, p] = await Promise.all([api.health(), api.state(), api.drift(), api.parserStatus()])
        setHealth(h); setState(s); setDrift(d); setParser(p)
      } catch (e) { setError(String(e.message || e)) }
    })()
    refreshForecast()
    refreshPlan()
    load(setBaseline, () => api.change('no_change'))
    load(setTrends, () => api.trends())
    api.replaySuggest().catch(() => {})   // warm the server-side cache for the Replay tab
  }, [load, refreshForecast, refreshPlan])

  const onCard = useCallback((card) => {
    setCards((c) => [{ ...card, at: Date.now() }, ...c])
    if (card.kind === 'change') setPendingChange(card.payload)
  }, [])

  const onAccepted = useCallback(async () => {
    try { setPlanned(await api.planned()) } catch (e) { /* ignore */ }
    refreshForecast()
    refreshPlan()
  }, [refreshForecast, refreshPlan])

  const onParser = useCallback((name) => setParser((p) => ({ ...(p || {}), last_parser: name })), [])

  return (
    <div className="app">
      <Header health={health} state={state} drift={drift} parser={parser} right={<Link to="/clinician" className="pill">Clinician view</Link>} />
      <div className="main">
        <div className="left">
          <nav className="tabs">
            {TABS.map((t) => <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}
          </nav>
          <div className="content">
            {error ? <div className="card"><div className="status error">Backend not reachable ({error}). Start it with <code>.\run_demo.ps1</code> (API on port 8000).</div></div> : null}
            {tab === 'Now' ? <NowTab state={state} forecast={forecast} history={history} /> : null}
            {tab === 'Today' ? <TodayTab cards={cards} planned={planned} plan={plan} alerts={alerts} onAccepted={onAccepted} /> : null}
            {tab === 'Body' ? <BodyTab state={state} baseline={baseline} pendingChange={pendingChange} /> : null}
            {tab === 'Trends' ? <TrendsTab trends={trends} /> : null}
            {tab === 'Replay' ? <ReplayTab /> : null}
          </div>
        </div>
        <aside className="right">
          <Chat onCard={onCard} onAccepted={onAccepted} onParser={onParser} onChange={(c) => setPendingChange(c)} goTo={setTab} parser={parser} twinNow={health?.now} />
        </aside>
      </div>
    </div>
  )
}
