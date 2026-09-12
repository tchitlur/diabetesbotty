import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Login from './components/Login.jsx'
import Header from './components/Header.jsx'
import Home from './components/Home.jsx'
import PlanTab from './components/PlanTab.jsx'
import DetailsTab from './components/DetailsTab.jsx'
import Chat from './components/Chat.jsx'

const TABS = ['Home', 'Plan', 'Details']
const idle = { data: null, loading: false, error: null }

// A tiny resource holder: { data, loading, error }. Screen data is fetched here so a
// tab switch never shows a blank card; the chat refreshes it when the plan changes.
export default function App() {
  const [profile, setProfile] = useState(null)      // null = login screen
  const [profiles, setProfiles] = useState([])
  const [tab, setTab] = useState('Home')
  const [health, setHealth] = useState(null)
  const [parser, setParser] = useState(null)
  const [home, setHome] = useState(idle)
  const [version, setVersion] = useState(0)          // bumps when accepted events change (Plan refetches)
  const [error, setError] = useState(null)
  const chatRef = useRef(null)

  const load = useCallback(async (setter, fn) => {
    setter((r) => ({ ...r, loading: true, error: null }))
    try { const data = await fn(); setter({ data, loading: false, error: null }) } catch (e) { setter({ data: null, loading: false, error: e.message || String(e) }) }
  }, [])
  const refreshHome = useCallback(() => load(setHome, () => api.home()), [load])

  const refreshProfiles = useCallback(async () => {
    try { setProfiles(await api.profiles()) } catch (e) { setError(String(e.message || e)) }
  }, [])

  useEffect(() => { refreshProfiles() }, [refreshProfiles])

  // after login: everything the screens need
  useEffect(() => {
    if (!profile) return
    setError(null)
    setHome(idle)
    ;(async () => {
      try {
        const [h, p] = await Promise.all([api.health(), api.parserStatus()])
        setHealth(h); setParser(p)
      } catch (e) { setError(String(e.message || e)) }
    })()
    refreshHome()
    api.plan(0).catch(() => {})   // warm the planner cache so "Plan my day" and /plan tomorrow are quick
  }, [profile, refreshHome])

  const onAccepted = useCallback(() => { refreshHome(); setVersion((v) => v + 1) }, [refreshHome])
  const onParser = useCallback((name) => setParser((p) => ({ ...(p || {}), last_parser: name })), [])

  const switchProfile = useCallback(async (id) => {
    if (!id || id === profile?.id) return
    const p = await api.selectProfile(id)
    chatRef.current?.reset()
    setTab('Home')
    setHome(idle)      // drop the previous person's data before the new one loads
    setProfile(p)
  }, [profile])

  const logout = useCallback(() => { chatRef.current?.reset(); setProfile(null); setTab('Home'); refreshProfiles() }, [refreshProfiles])

  if (!profile) return <Login profiles={profiles} error={error} onEnter={async (p) => { await api.selectProfile(p.id); setProfile(p) }} onCreated={(p) => { setProfiles((l) => [...l, p]); setProfile(p) }} />

  return (
    <div className="app">
      <Header profile={profile} profiles={profiles} home={home.data} health={health} onSwitch={switchProfile} onLogout={logout}
              onQuick={(action) => chatRef.current?.quick(action)} parser={parser} tab={tab} setTab={setTab} tabs={TABS} />
      <div className="main">
        <div className="content">
          <div className="inner">
            {error ? <div className="card"><div className="status error">Backend not reachable ({error}). Start it with <code>.\run_demo.ps1</code> (API on port 8000).</div></div> : null}
            {tab === 'Home' ? <Home home={home} onTile={null} nowIso={health?.now} /> : null}
            {tab === 'Plan' ? <PlanTab version={version} nowIso={health?.now} onAccepted={onAccepted} /> : null}
            {tab === 'Details' ? <DetailsTab profile={profile} parser={parser} health={health} home={home} /> : null}
          </div>
        </div>
        <aside className="right">
          <Chat ref={chatRef} onAccepted={onAccepted} onParser={onParser} goTo={setTab} parser={parser} twinNow={health?.now} />
        </aside>
      </div>
    </div>
  )
}
