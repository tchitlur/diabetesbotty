import React, { useEffect, useRef, useState } from 'react'
import { api, fmtTime, pct } from '../api.js'
import PermissionCard from './PermissionCard.jsx'
import ChangeCard from './ChangeCard.jsx'
import TapBar from './TapBar.jsx'
import EventSummary from './EventSummary.jsx'

const HELP = 'Ask about anything you are about to do, for example "can I have two more beers tonight?" or "fasted run tomorrow at 7 for 30 min". Commands: /change morning_workouts (or cut_caffeine, drink_fridays_only, fasting_16_8), /plan tomorrow, /budget, /why.'

function Bot({ children }) { return <div className="msg bot">{children}</div> }

export default function Chat({ onCard, onAccepted, onParser, onChange, goTo, parser, twinNow }) {
  const [log, setLog] = useState([{ id: 0, role: 'bot', node: <span>{HELP}</span> }])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const fileRef = useRef(null)
  const endRef = useRef(null)
  const idRef = useRef(1)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [log, busy])
  const push = (role, node) => { const id = idRef.current++; setLog((l) => [...l, { id, role, node }]); return id }
  const replace = (id, node) => setLog((l) => l.map((m) => (m.id === id ? { ...m, node } : m)))
  const remove = (id) => setLog((l) => l.filter((m) => m.id !== id))
  const photoOk = !!parser?.gemini_configured

  const runPermission = async (parsed) => {
    const badge = <span className={`badge ${parsed.parser}`}>Parser: {parsed.parser === 'gemini' ? 'Gemini' : 'local fallback'}</span>
    onParser && onParser(parsed.parser)
    push('bot', <div>{badge} <span className="muted small">parse confidence {pct(parsed.confidence)}{parsed.notes ? ` · ${parsed.notes}` : ''}</span><EventSummary event={parsed.event} /></div>)
    const id = push('bot', <span className="status"><span className="spinner" />Simulating: do nothing, as proposed, and every variant, 200 Monte Carlo runs each…</span>)
    try {
      const card = await api.permission(parsed.event)
      replace(id, <PermissionCard card={card} onAccepted={onAccepted} onWhy={() => runWhy()} />)
      onCard && onCard({ kind: 'permission', payload: card })
    } catch (e) { replace(id, <span className="err">The simulation failed: {String(e.message)}</span>) }
  }

  const runWhy = async () => {
    const id = push('bot', <span className="status"><span className="spinner" />Fetching the explanation of the last card…</span>)
    try {
      const w = await api.why()
      if (!w.verdict) { replace(id, <span>{w.message}</span>); return }
      replace(id, <div>
        <b>/why</b> — explanation of the last card
        <div className="evgrid">
          <span className="k">verdict</span><span className="v">{w.verdict.replace(/_/g, ' ')}</span>
          <span className="k">condition</span><span className="v">{w.condition || '–'}</span>
          <span className="k">confidence</span><span className="v">{pct(w.confidence)}</span>
          <span className="k">gate</span><span className="v">{w.gate?.action} · {w.gate?.reason}</span>
        </div>
        {w.factors?.length ? <div className="small" style={{ marginTop: 'var(--s2)' }}><b>Top factors</b> (|correlation| with the glucose low point across the Monte Carlo runs):<ul style={{ margin: '4px 0 0 18px', padding: 0 }}>{w.factors.map((f) => <li key={f.name}>{f.name}: {f.effect} (weight {f.weight.toFixed(2)})</li>)}</ul></div> : null}
        <div className="small" style={{ marginTop: 'var(--s2)' }}><b>Data used:</b> {w.data_used.join('; ')}</div>
        <div className="small"><b>Data missing:</b> {w.data_missing.join('; ')}</div>
        {w.explanation ? <div className="small" style={{ marginTop: 'var(--s2)' }}>{w.explanation}</div> : null}
        <details><summary>full explanation payload (JSON)</summary><pre>{JSON.stringify(w, null, 2)}</pre></details>
      </div>)
    } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
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
        const id = push('bot', <span className="status"><span className="spinner" />Rewriting the representative week, simulating 30 days and 10 years…</span>)
        try {
          const r = await api.change(name)
          replace(id, <ChangeCard resp={r} compact />)
          onChange && onChange(r)
          onCard && onCard({ kind: 'change', payload: r })
          push('bot', <span className="muted small">The Body tab now has a "pending change" view for {name}; the Today tab has the full 22-row table.</span>)
        } catch (e) { replace(id, <span className="err">{String(e.message)}. Options: morning_workouts, cut_caffeine, drink_fridays_only, fasting_16_8, no_change.</span>) }
      } else if (t.startsWith('/plan')) {
        const m = t.match(/(\d+)\s*drink/); const drinks = m ? +m[1] : 0
        const id = push('bot', <span className="status"><span className="spinner" />Grid-searching workout time, snack and drink cutoff for tomorrow…</span>)
        try {
          const p = await api.plan(drinks)
          replace(id, <div><b>/plan tomorrow</b> ({p.date}): workout at <b>{fmtTime(p.workout_start)}</b>{p.snack_time ? <>, snack at <b>{fmtTime(p.snack_time)}</b></> : ', no snack needed'}{p.drink_cutoff ? <>, last drink by <b>{fmtTime(p.drink_cutoff)}</b></> : ''}. P(hypo) around the workout {pct(p.p_hypo)}, time in range {pct(p.tir)}.<div className="muted small" style={{ marginTop: 4 }}>{p.notes.join(' ')}</div><div className="muted small">The hourly timeline is in the Today tab.</div></div>)
          goTo && goTo('Today')
        } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
      } else if (t.startsWith('/budget')) {
        const id = push('bot', <span className="status"><span className="spinner" />Solving the weekly budget for a 5 % risk headroom…</span>)
        try {
          const b = await api.budget()
          replace(id, <div><b>/budget</b> — weekly allowances that keep 10-year organ risk within 5 % of your current trajectory:
            <div className="stats" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 'var(--s2)', margin: 'var(--s2) 0' }}>
              <div style={{ background: 'var(--panel-3)', borderRadius: 6, padding: 'var(--s2)' }}><span className="muted xs">alcohol</span><br /><b style={{ fontSize: 'var(--fs-lg)' }}>{Math.round(b.alcohol_g_per_week)} g</b><br /><span className="muted xs">≈ {(b.alcohol_g_per_week / 14).toFixed(1)} drinks</span></div>
              <div style={{ background: 'var(--panel-3)', borderRadius: 6, padding: 'var(--s2)' }}><span className="muted xs">caffeine</span><br /><b style={{ fontSize: 'var(--fs-lg)' }}>{Math.round(b.caffeine_mg_per_week)} mg</b><br /><span className="muted xs">≈ {(b.caffeine_mg_per_week / 95).toFixed(1)} coffees</span></div>
              <div style={{ background: 'var(--panel-3)', borderRadius: 6, padding: 'var(--s2)' }}><span className="muted xs">off-plan meals</span><br /><b style={{ fontSize: 'var(--fs-lg)' }}>{b.off_plan_meals_per_week}</b><br /><span className="muted xs">unbolused</span></div>
            </div>
            <span className="muted small">10-year mean organ risk {pct(b.baseline_risk, 1)} now → {pct(b.risk_at_budget, 1)} at the full budget (tolerance {pct(b.tolerance)}).</span></div>)
        } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
      } else if (t.startsWith('/why')) {
        await runWhy()
      } else if (t.startsWith('/help')) {
        push('bot', <span>{HELP}</span>)
      } else {
        const id = push('bot', <span className="status"><span className="spinner" />Parsing…</span>)
        try {
          const parsed = await api.parse(t)
          remove(id)
          await runPermission(parsed)
        } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
      }
    } finally { setBusy(false) }
  }

  const onTap = async (event) => {
    if (busy) return
    push('user', `[tap] ${event.label}`)
    setBusy(true)
    try { await runPermission({ event, parser: 'local', confidence: 1.0, notes: 'tap input, nothing to parse' }) } finally { setBusy(false) }
  }

  const onPhoto = async (file) => {
    if (!file || busy) return
    push('user', `[photo] ${file.name}`)
    setBusy(true)
    const id = push('bot', <span className="status"><span className="spinner" />Estimating nutrition from the photo…</span>)
    try {
      const parsed = await api.parseImage(file)
      remove(id)
      await runPermission(parsed)
    } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) } finally { setBusy(false) }
  }

  return (
    <div className="chat">
      <div className="log">
        {log.map((m) => (m.role === 'user' ? <div key={m.id} className="msg user">{m.node}</div> : <Bot key={m.id}>{m.node}</Bot>))}
        <div ref={endRef} />
      </div>
      <TapBar onTap={onTap} disabled={busy} twinNow={twinNow} />
      <form onSubmit={(e) => { e.preventDefault(); submit() }}>
        <input type="text" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); submit() } }} placeholder="can I have two more beers tonight?" disabled={busy} aria-label="chat message" />
        <input ref={fileRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={(e) => { onPhoto(e.target.files?.[0]); e.target.value = '' }} />
        <button type="button" onClick={() => fileRef.current?.click()} disabled={busy || !photoOk} title={photoOk ? 'Photo of a meal: Gemini estimates the nutrition' : 'Photo input needs a Gemini key (scripts\\setup_key.ps1); the local parser cannot see images'}>📷</button>
        <button type="submit" className="primary" disabled={busy}>Ask</button>
      </form>
      <div className="hint">/change morning_workouts · /plan tomorrow · /budget · /why · /help</div>
    </div>
  )
}
