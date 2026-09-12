import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { api, fmtTime, fmtRel, eventPhrase, shiftIso } from '../api.js'
import AnswerCard from './AnswerCard.jsx'
import ChangeCard from './ChangeCard.jsx'
import QuickLog from './QuickLog.jsx'
import HelpPopover, { CHANGES } from './HelpPopover.jsx'

const PLACEHOLDER = 'Ask before you eat, drink, or move…'
const changeLabel = (name) => (CHANGES.find(([n]) => n === name) || [name, name])[1]

function Understood({ event, nowIso, parsed }) {
  return (
    <div className="msg plain">
      <div className="understood"><span>Understood:</span><b>{eventPhrase(event)} {fmtRel(event.start_time, nowIso)}</b>{parsed?.parser ? <span className="faint xs">· read by {parsed.parser === 'gemini' ? 'Gemini' : 'the built-in reader'}</span> : null}</div>
      <details><summary>details</summary><pre>{JSON.stringify(event, null, 2)}</pre></details>
    </div>
  )
}

const Chat = forwardRef(function Chat({ onAccepted, onParser, goTo, parser, twinNow }, ref) {
  const [log, setLog] = useState([])
  const [help, setHelp] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)
  const idRef = useRef(1)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [log, busy])
  const push = (role, node) => { const id = idRef.current++; setLog((l) => [...l, { id, role, node }]); return id }
  const replace = (id, node) => setLog((l) => l.map((m) => (m.id === id ? { ...m, node } : m)))
  const remove = (id) => setLog((l) => l.filter((m) => m.id !== id))
  const nowIso = twinNow

  const stripFor = (card) => {
    const mc = card.mini_curve
    if (!mc) return null
    return { times: mc.times, line: mc.best_variant, p10: mc.p10, p90: mc.p90, markerIso: card.proposed?.start_time, markerLabel: eventPhrase(card.proposed), hours: 6, nowLabel: fmtTime(nowIso), title: 'Next 6 hours if you follow the advice' }
  }

  const runPermission = async (event, parsed) => {
    if (parsed?.parser) onParser && onParser(parsed.parser)
    const ev = { ...event, start_time: event.start_time === 'now' ? (nowIso || event.start_time) : event.start_time }
    push('bot', <Understood event={ev} nowIso={nowIso} parsed={parsed} />)
    const id = push('bot', <span className="status"><span className="spinner" />Checking how your body would handle it…</span>)
    try {
      const card = await api.permission(ev)
      replace(id, <AnswerCard plain={card.plain} strip={stripFor(card)} card={card} onAccepted={onAccepted} onWhy={() => runWhy()} details={<pre>{JSON.stringify({ verdict: card.verdict, condition: card.condition, options: card.variants, confidence: card.confidence, data_used: card.data_used, data_missing: card.data_missing }, null, 2)}</pre>} />)
    } catch (e) { replace(id, <span className="err">Could not check that: {String(e.message)}</span>) }
  }

  const runWhy = async () => {
    const id = push('bot', <span className="status"><span className="spinner" />Getting the reason…</span>)
    try {
      const w = await api.why()
      if (!w.plain) { replace(id, <span>Nothing to explain yet. Ask about something first.</span>); return }
      replace(id, <AnswerCard plain={{ ...w.plain, headline: `Why: ${w.plain.headline}` }} details={<pre>{JSON.stringify({ verdict: w.verdict, condition: w.condition, confidence: w.confidence, factors: w.factors, data_used: w.data_used, data_missing: w.data_missing, gate: w.gate }, null, 2)}</pre>} />)
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
        const id = push('bot', <span className="status"><span className="spinner" />Trying that change on a typical week and running it forward 30 days…</span>)
        try {
          const r = await api.change(name)
          replace(id, <ChangeCard resp={r} />)
        } catch (e) { replace(id, <span className="err">{String(e.message)}. Options: {CHANGES.map(([n, l]) => `${l} (/change ${n})`).join(', ')}.</span>) }
      } else if (t.startsWith('/plan')) {
        const m = t.match(/(\d+)\s*drink/); const drinks = m ? +m[1] : 0
        const id = push('bot', <span className="status"><span className="spinner" />Trying every workout time tomorrow…</span>)
        try {
          const p = await api.plan(drinks)
          const start = p.workout_start ? shiftIso(p.workout_start, -60) : null
          const strip = p.glucose_times?.length ? { times: p.glucose_times, line: p.glucose_median, p10: p.glucose_p10, p90: p.glucose_p90, startIso: start, markerIso: p.workout_start, markerLabel: 'workout', hours: 6, title: 'Around the workout tomorrow' } : null
          replace(id, <AnswerCard plain={p.plain} strip={strip} footer={<button className="small ghost" onClick={() => goTo && goTo('Plan')}>open the Plan tab</button>} details={<pre>{JSON.stringify({ workout_start: p.workout_start, snack_time: p.snack_time, drink_cutoff: p.drink_cutoff, notes: p.notes }, null, 2)}</pre>} />)
        } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
      } else if (t.startsWith('/budget')) {
        push('bot', <span>The /budget command is not part of this version. Try /plan tomorrow or /change morning_workouts.</span>)
      } else if (t.startsWith('/why')) {
        await runWhy()
      } else if (t.startsWith('/help')) {
        setHelp(true)
      } else {
        const id = push('bot', <span className="status"><span className="spinner" />Reading that…</span>)
        try {
          const parsed = await api.parse(t)
          remove(id)
          await runPermission(parsed.event, parsed)
        } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
      }
    } finally { setBusy(false) }
  }

  const onQuick = async (a) => {
    if (busy) return
    if (a.text) { await submit(a.text); return }
    setBusy(true)
    try {
      if (a.file) {
        push('user', `photo: ${a.file.name}`)
        const id = push('bot', <span className="status"><span className="spinner" />Looking at the photo…</span>)
        try { const parsed = await api.parseImage(a.file); remove(id); await runPermission(parsed.event, parsed) } catch (e) { replace(id, <span className="err">{String(e.message)}</span>) }
      } else if (a.event) {
        push('user', a.event.label)
        await runPermission(a.event, { parser: null })
      }
    } finally { setBusy(false) }
  }

  useImperativeHandle(ref, () => ({
    quick: onQuick,
    ask: (t) => submit(t),
    reset: () => { setLog([]); setText('') },
  }))

  return (
    <div className="chat">
      <div className="log">
        {log.length === 0 ? <div className="msg plain faint">Nothing asked yet. Try "Can I have pizza for dinner?" or tap a button below.</div> : null}
        {log.map((m) => (m.role === 'user' ? <div key={m.id} className="msg user">{m.node}</div> : <div key={m.id} className={m.node?.props?.className === 'msg plain' ? '' : 'msg bot'}>{m.node}</div>))}
        <div ref={endRef} />
      </div>
      <QuickLog onAction={onQuick} disabled={busy} parser={parser} />
      <form onSubmit={(e) => { e.preventDefault(); submit() }}>
        <input type="text" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); submit() } }} placeholder={PLACEHOLDER} disabled={busy} aria-label="chat message" />
        <button type="button" className="icon" aria-label="help" title="Examples and commands" onClick={() => setHelp((x) => !x)}>?</button>
        <button type="submit" className="primary" disabled={busy}>Ask</button>
        {help ? <HelpPopover onPick={(x) => { setHelp(false); setText(x) }} onClose={() => setHelp(false)} /> : null}
      </form>
    </div>
  )
})

export default Chat
