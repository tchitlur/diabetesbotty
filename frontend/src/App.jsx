import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Login from './components/Login.jsx'
import Header from './components/Header.jsx'
import Home from './components/Home.jsx'
import Chat from './components/Chat.jsx'
import Sheet from './components/Sheet.jsx'
import { useMobile } from './hooks.js'

// Plan and Details are loaded on first use (phones over a tunnel: Home paints first).
const PlanTab = lazy(() => import('./components/PlanTab.jsx'))
const DetailsTab = lazy(() => import('./components/DetailsTab.jsx'))

const TABS = ['Home', 'Plan', 'Details']
const idle = { data: null, loading: false, error: null }

// A tiny resource holder: { data, loading, error }. Screen data is fetched here so a
// tab switch never shows a blank card; the chat refreshes it when the plan changes.
export default function App() {
  const [profile, setProfile] = useState(null)      // null = login screen
  const [profiles, setProfiles] = useState([])
  const [adding, setAdding] = useState(false)       // login screen opened on the "add someone" form
  const [tab, setTab] = useState('Home')
  const [health, setHealth] = useState(null)
  const [parser, setParser] = useState(null)
  const [home, setHome] = useState(idle)
  const [version, setVersion] = useState(0)          // bumps when accepted events change (Plan refetches)
  const [error, setError] = useState(null)
  const [chatHidden, setChatHidden] = useState(false) // desktop: "hide ▸"
  const [chatOpen, setChatOpen] = useState(false)     // phone: the full-screen chat sheet
  const chatRef = useRef(null)
  const mobile = useMobile()

  const load = useCallback(async (setter, fn) => {
    setter((r) => ({ ...r, loading: true, error: null }))
    try { const data = await fn(); setter({ data, loading: false, error: null }) } catch (e) { setter({ data: null, loading: false, error: e.message || String(e) }) }
  }, [])
  const refreshHome = useCallback(() => load(setHome, () => api.home()), [load])

  const refreshProfiles = useCallback(async () => {
    try { setProfiles(await api.profiles()) } catch (e) { setError(String(e.message || e)) }
  }, [])

  useEffect(() => { refreshProfiles() }, [refreshProfiles])

  // after login: everything the screens need (Home is one request; the header clock is another small one)
  useEffect(() => {
    if (!profile) return undefined
    setError(null)
    setHome(idle)
    ;(async () => {
      try {
        const [h, p] = await Promise.all([api.health(), api.parserStatus()])
        setHealth(h); setParser(p)
      } catch (e) { setError(String(e.message || e)) }
    })()
    refreshHome()
    api.plan(0).catch(() => {})   // warm the planner cache so "Suggest my day" and /plan tomorrow are quick
    // live: every 60 s re-read the sensor (the backend follows the wall clock) and the header clock
    const id = setInterval(() => { refreshHome(); api.health().then(setHealth).catch(() => {}) }, 60_000)
    return () => clearInterval(id)
  }, [profile, refreshHome])

  const onAccepted = useCallback(() => { refreshHome(); setVersion((v) => v + 1) }, [refreshHome])
  const onParser = useCallback((name) => setParser((p) => ({ ...(p || {}), last_parser: name })), [])
  const setAiReader = useCallback(async (on) => { setParser(await api.parserMode(on)) }, [])

  const switchProfile = useCallback(async (id) => {
    if (!id || id === profile?.id) return
    const p = await api.selectProfile(id)
    chatRef.current?.reset()
    setTab('Home')
    setHome(idle)      // drop the previous person's data before the new one loads
    setProfile(p)
  }, [profile])
  const onCreated = useCallback((p) => { setProfiles((l) => [...l.filter((x) => x.id !== p.id), p]); chatRef.current?.reset(); setTab('Home'); setHome(idle); setProfile(p); setAdding(false) }, [])
  const goAdd = useCallback(() => { chatRef.current?.reset(); setProfile(null); setTab('Home'); setAdding(true); refreshProfiles() }, [refreshProfiles])

  if (!profile) return <Login profiles={profiles} error={error} startAdding={adding} onEnter={async (p) => { await api.selectProfile(p.id); setAdding(false); setProfile(p) }} onCreated={onCreated} />

  const chat = <Chat ref={chatRef} onAccepted={onAccepted} onParser={onParser} goTo={(t) => { setTab(t); if (mobile) setChatOpen(false) }} parser={parser} twinNow={health?.now}
                     onHide={mobile ? () => setChatOpen(false) : () => setChatHidden(true)} onAiReader={setAiReader} mobile={mobile} signature={profile.signature} />
  const fallback = <div className="card"><div className="status"><span className="spinner" />Loading…</div></div>

  return (
    <div className={`app ${mobile ? 'mobile' : ''} ${chatHidden && !mobile ? 'chat-hidden' : ''}`}>
      <Header profile={profile} profiles={profiles} home={home.data} health={health} onSwitch={switchProfile} onCreated={onCreated} onAdd={goAdd}
              onQuick={(action) => { if (mobile) setChatOpen(true); setTimeout(() => chatRef.current?.quick(action), 0) }} parser={parser} tab={tab} setTab={setTab} tabs={TABS} mobile={mobile} />
      {mobile ? <nav className="mtabs" data-testid="mtabs">{TABS.map((t) => <button key={t} type="button" className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}</nav> : null}
      <div className="main">
        <div className="content">
          <div className="inner">
            {error ? <div className="card"><div className="status error">Backend not reachable ({error}). Start it with <code>.\run_demo.ps1</code> (API on port 8000).</div></div> : null}
            {tab === 'Home' ? <Home home={home} onTile={null} nowIso={health?.now} /> : null}
            {tab === 'Plan' ? <Suspense fallback={fallback}><PlanTab version={version} nowIso={health?.now} onAccepted={onAccepted} mobile={mobile} /></Suspense> : null}
            {tab === 'Details' ? <Suspense fallback={fallback}><DetailsTab profile={profile} parser={parser} health={health} home={home} mobile={mobile} /></Suspense> : null}
          </div>
        </div>
        {!mobile && !chatHidden ? <aside className="right">{chat}</aside> : null}
        {!mobile && chatHidden ? <button type="button" className="show-chat" onClick={() => setChatHidden(false)} data-testid="show-chat">◂ Ask your twin</button> : null}
      </div>
      {mobile && !chatOpen ? <button type="button" className="ask-fab" onClick={() => setChatOpen(true)} data-testid="ask-fab">💬 Ask</button> : null}
      {mobile && chatOpen ? <Sheet full hideHead title="Ask your twin" onClose={() => setChatOpen(false)} testId="chat-sheet">{chat}</Sheet> : null}
    </div>
  )
}
