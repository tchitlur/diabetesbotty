import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import PermissionCard from './PermissionCard.jsx'
import ChangeCard from './ChangeCard.jsx'
import TapBar from './TapBar.jsx'

const HELP = 'Ask about anything you are about to do ("can I have two more beers tonight?", "fasted run tomorrow at 7 for 30 min"), or use /change <morning_workouts|cut_caffeine|drink_fridays_only|fasting_16_8>, /plan tomorrow, /budget, /why.'

function Bot({ children }) { return <div className="msg bot">{children}</div> }

export default function Chat({ onCard, onAccepted, onParser, onChange, goTo }) {
  const [log, setLog] = useState([{ id: 0, role: 'bot', node: <span>{HELP}</span> }])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const fileRef = useRef(null)
  const endRef = useRef(null)
  const idRef = useRef(1)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [log])
  const push = (role, node) => { const id = idRef.current++; setLog((l) => [...l, { id, role, node }]); return id }
  const replace = (id, node) => setLog((l) => l.map((m) => (m.id === id ? { ...m, node } : m)))

  const runPermission = async (parsed) => {
    const badge = <span className={`badge ${parsed.parser}`}>Parser: {parsed.parser === 'gemini' ? 'Gemini' : 'local fallback'}</span>
    onParser && onParser(parsed.parser)
    push('bot', <div>{badge} <span className="muted">confidence {parsed.confidence.toFixed(2)}{parsed.notes ? ` · ${parsed.notes}` : ''}</span><pre>{JSON.stringify(parsed.event, null, 2)}</pre></div>)
    const id = push('bot', <span><span className="spinner" />simulating… (do nothing, as proposed, 4 variants × 200 Monte Carlo runs)</span>)
    try {
      const card = await api.permission(parsed.event)
      replace(id, <PermissionCard card={card} onAccepted={onAccepted} onWhy={() => runWhy()} />)
      onCard && onCard({ kind: 'permission', payload: card })
    } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
  }

  const runWhy = async () => {
    const id = push('bot', <span><span className="spinner" />fetching explanation…</span>)
    try { const w = await api.why(); replace(id, <div><b>/why</b> — explanation payload of the last card<pre>{JSON.stringify(w, null, 2)}</pre></div>) } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
  }

  const submit = async (raw) => {
    const t = (raw ?? text).trim()
    if (!t || busy) return
    setText('')
    push('user', t)
    setBusy(true)
    try {
      if (t.startsWith('/change')) {
        const name = t.split(/\s+/)[1] || 'no_change'
        const id = push('bot', <span><span className="spinner" />rewriting the representative week, simulating 30 days + 10 years…</span>)
        try {
          const r = await api.change(name)
          replace(id, <ChangeCard resp={r} />)
          onChange && onChange(r)
          onCard && onCard({ kind: 'change', payload: r })
          push('bot', <span className="muted">Body tab now has a "pending change" toggle for {name}.</span>)
        } catch (e) { replace(id, <span className="err">{String(e.message)} — options: morning_workouts, cut_caffeine, drink_fridays_only, fasting_16_8, no_change</span>) }
      } else if (t.startsWith('/plan')) {
        const m = t.match(/(\d+)\s*drink/); const drinks = m ? +m[1] : 0
        const id = push('bot', <span><span className="spinner" />grid-searching workout time, snack and drink cutoff…</span>)
        try {
          const p = await api.plan(drinks)
          replace(id, <div><b>/plan tomorrow</b> ({p.date}): workout <b>{p.workout_start?.slice(11, 16)}</b>{p.snack_time ? <>, snack at <b>{p.snack_time.slice(11, 16)}</b></> : ', no snack needed'}{p.drink_cutoff ? <>, last drink by <b>{p.drink_cutoff.slice(11, 16)}</b></> : ''}. P(hypo) around the workout {(100 * p.p_hypo).toFixed(0)} %, day TIR {(100 * p.tir).toFixed(0)} %.<div className="muted" style={{ marginTop: 4 }}>{p.notes.join(' ')}</div><div className="muted">Timeline is in the Today tab.</div></div>)
          goTo && goTo('Today')
        } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
      } else if (t.startsWith('/budget')) {
        const id = push('bot', <span><span className="spinner" />solving weekly budget for 5 % risk headroom…</span>)
        try {
          const b = await api.budget()
          replace(id, <div><b>/budget</b> — weekly allowances that keep 10-year organ risk within 5 % of your current trajectory:
            <div className="stats" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, margin: '8px 0' }}>
              <div style={{ background: 'var(--panel-2)', borderRadius: 6, padding: 6 }}><span className="muted">alcohol</span><br /><b style={{ fontSize: 18 }}>{b.alcohol_g_per_week.toFixed(0)} g</b><br /><span className="muted">≈ {(b.alcohol_g_per_week / 14).toFixed(1)} drinks</span></div>
              <div style={{ background: 'var(--panel-2)', borderRadius: 6, padding: 6 }}><span className="muted">caffeine</span><br /><b style={{ fontSize: 18 }}>{b.caffeine_mg_per_week.toFixed(0)} mg</b><br /><span className="muted">≈ {(b.caffeine_mg_per_week / 95).toFixed(1)} coffees</span></div>
              <div style={{ background: 'var(--panel-2)', borderRadius: 6, padding: 6 }}><span className="muted">off-plan meals</span><br /><b style={{ fontSize: 18 }}>{b.off_plan_meals_per_week}</b><br /><span className="muted">unbolused</span></div>
            </div>
            <span className="muted">baseline risk {(100 * b.baseline_risk).toFixed(2)} % → at budget {(100 * b.risk_at_budget).toFixed(2) } % (tolerance {(100 * b.tolerance).toFixed(0)} %)</span></div>)
        } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
      } else if (t.startsWith('/why')) {
        await runWhy()
      } else if (t.startsWith('/help')) {
        push('bot', <span>{HELP}</span>)
      } else {
        const id = push('bot', <span><span className="spinner" />parsing…</span>)
        try {
          const parsed = await api.parse(t)
          setLog((l) => l.filter((m) => m.id !== id))
          await runPermission(parsed)
        } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
      }
    } finally { setBusy(false) }
  }

  const onTap = async (event) => {
    if (busy) return
    push('user', `[tap] ${event.label}`)
    setBusy(true)
    try { await runPermission({ event, parser: 'local', confidence: 1.0, notes: 'tap input (no parsing)' }) } finally { setBusy(false) }
  }

  const onPhoto = async (file) => {
    if (!file || busy) return
    push('user', `[photo] ${file.name}`)
    setBusy(true)
    const id = push('bot', <span><span className="spinner" />estimating nutrition from the photo…</span>)
    try {
      const parsed = await api.parseImage(file)
      setLog((l) => l.filter((m) => m.id !== id))
      await runPermission(parsed)
    } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) } finally { setBusy(false) }
  }

  return (
    <div className="chat">
      <div className="log">
        {log.map((m) => (m.role === 'user' ? <div key={m.id} className="msg user">{m.node}</div> : <Bot key={m.id}>{m.node}</Bot>))}
        <div ref={endRef} />
      </div>
      <TapBar onTap={onTap} disabled={busy} />
      <form onSubmit={(e) => { e.preventDefault(); submit() }}>
        <input type="text" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); submit() } }} placeholder="can I have two more beers tonight?" disabled={busy} />
        <input ref={fileRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={(e) => { onPhoto(e.target.files?.[0]); e.target.value = '' }} />
        <button type="button" onClick={() => fileRef.current?.click()} disabled={busy} title="photo of a meal">📷</button>
        <button type="submit" className="send" disabled={busy}>Ask</button>
      </form>
      <div className="hint">/change morning_workouts · /plan tomorrow · /budget · /why</div>
    </div>
  )
}
