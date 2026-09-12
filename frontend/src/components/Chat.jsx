import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { api, fmtTime, fmtRel, eventPhrase, shiftIso } from '../api.js'
import AnswerCard from './AnswerCard.jsx'
import ChangeCard from './ChangeCard.jsx'
import QuickLog from './QuickLog.jsx'
import HelpPopover, { CHANGES } from './HelpPopover.jsx'
import { ToolChips, StateCard, ForecastCard, ExplainCard, HistoryCard, LoggedCard, TextCard } from './ChatCards.jsx'

const PLACEHOLDER = 'Ask your personalized model about your daily decisions.'

function Understood({ text, parser }) {
  return (
    <div className="msg plain">
      <div className="understood"><span>{text.split(':')[0]}:</span><b>{text.split(':').slice(1).join(':').trim()}</b>{parser ? <span className="faint xs">· read by {parser === 'gemini' ? 'Gemini' : 'the built-in reader'}</span> : null}</div>
    </div>
  )
}

// Every message goes to /chat: Gemini (or the built-in reader) picks backend tools, the backend
// phrases and ground-checks the answer, and the card that comes back is rendered by type. The
// quick buttons and photos still go straight to the permission engine (same card as before).
const Chat = forwardRef(function Chat({ onAccepted, onParser, goTo, parser, twinNow, onHide, onAiReader, mobile = false, signature }, ref) {
  const [log, setLog] = useState([])
  const [help, setHelp] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [aiBusy, setAiBusy] = useState(false)
  const endRef = useRef(null)
  const inputRef = useRef(null)
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
  const permissionNode = (card, extra) => (
    <AnswerCard plain={card.plain} strip={stripFor(card)} card={card} onAccepted={onAccepted} onWhy={() => submit('/why')} footer={extra}
                details={<pre>{JSON.stringify({ verdict: card.verdict, condition: card.condition, options: card.variants, confidence: card.confidence, data_used: card.data_used, data_missing: card.data_missing, engine: card.engine }, null, 2)}</pre>} />
  )
  const planNode = (p) => {
    const start = p.workout_start ? shiftIso(p.workout_start, -60) : null
    const strip = p.glucose_times?.length ? { times: p.glucose_times, line: p.glucose_median, p10: p.glucose_p10, p90: p.glucose_p90, startIso: start, markerIso: p.workout_start, markerLabel: 'workout', hours: 6, title: 'Around the workout tomorrow' } : null
    return <AnswerCard plain={p.plain} strip={strip} footer={<button className="small ghost" onClick={() => goTo && goTo('Plan')}>open the Plan tab</button>} details={<pre>{JSON.stringify({ workout_start: p.workout_start, snack_time: p.snack_time, drink_cutoff: p.drink_cutoff, notes: p.notes }, null, 2)}</pre>} />
  }

  // the bot's turn: answer text, the card for its type, the tool chips
  const Answer = ({ r }) => {
    const c = r.card || { type: 'text', payload: {} }
    const p = c.payload || {}
    let card = null
    if (c.type === 'permission') card = permissionNode(p)
    else if (c.type === 'plan') card = planNode(p)
    else if (c.type === 'change') card = <ChangeCard resp={p} />
    else if (c.type === 'state') card = <StateCard p={p} />
    else if (c.type === 'forecast') card = <ForecastCard p={p} nowIso={nowIso} />
    else if (c.type === 'explain') card = <ExplainCard p={p} />
    else if (c.type === 'history') card = <HistoryCard p={p} />
    else if (c.type === 'logged') card = <LoggedCard p={p} />
    else if (c.type === 'text') card = <TextCard p={p} />
    const showText = !(c.type === 'permission' || c.type === 'plan' || c.type === 'change')
    return (
      <div className="answer-wrap" data-card={c.type} data-testid={`answer-${c.type}`}>
        {showText ? <div className="answer-text">{r.answer}</div> : null}
        {card}
        <ToolChips tools={r.tools} router={r.router} />
        {r.grounding && r.grounding.replaced ? <div className="faint xs">The language model's wording was replaced: it used a number the tools did not return.</div> : null}
      </div>
    )
  }

  const runPermission = async (event, parsed) => {
    if (parsed?.parser) onParser && onParser(parsed.parser)
    const ev = { ...event, start_time: event.start_time === 'now' ? (nowIso || event.start_time) : event.start_time }
    push('bot', <Understood text={`Understood: ${eventPhrase(ev)} ${fmtRel(ev.start_time, nowIso)}`} parser={parsed?.parser} />)
    const id = push('bot', <span className="status"><span className="spinner" />Checking how your body would handle it…</span>)
    try {
      const card = await api.permission(ev)
      replace(id, <div className="answer-wrap" data-card="permission" data-testid="answer-permission">{permissionNode(card)}<ToolChips tools={['evaluate_action']} /></div>)
    } catch (e) { replace(id, <span className="err">Could not check that: {String(e.message)}</span>) }
  }

  const submit = async (raw) => {
    const t = (raw ?? text).trim()
    if (!t || busy) return
    setText('')
    push('user', t)
    setBusy(true)
    try {
      if (t.startsWith('/help')) { setHelp(true); return }
      if (t.startsWith('/budget')) { push('bot', <span>The /budget command is not part of this version. Try /plan tomorrow or /change morning_workouts.</span>); return }
      const id = push('bot', <span className="status"><span className="spinner" />{t.startsWith('/change') ? 'Trying that change on a typical week and running it forward 30 days…' : t.startsWith('/plan') ? 'Trying every workout time tomorrow…' : 'Asking your model…'}</span>)
      try {
        const r = await api.chat(t)
        if (r.router) onParser && onParser(r.router === 'gemini' ? 'gemini' : 'local')
        remove(id)
        if (r.understood) push('bot', <Understood text={r.understood} parser={r.router} />)
        push('bot', <Answer r={r} />)
        if (r.card?.type === 'logged' || r.card?.type === 'permission') onAccepted && onAccepted()
      } catch (e) { replace(id, <span className="err">{String(e.message)}{t.startsWith('/change') ? ` Options: ${CHANGES.map(([n, l]) => `${l} (/change ${n})`).join(', ')}.` : ''}</span>) }
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
    reset: () => { setLog([]); setText(''); api.chatReset().catch(() => {}) },
  }))

  const aiOn = !!parser?.ai_reader && !!parser?.key_present
  const toggleAi = async () => {
    if (aiBusy || !onAiReader) return
    setAiBusy(true)
    try { await onAiReader(!parser?.ai_reader) } finally { setAiBusy(false) }
  }
  return (
    <div className={`chat ${mobile ? 'mobile' : ''}`}>
      <div className="chat-head" data-testid="chat-head">
        <b>Ask your twin</b>
        <span className="chat-sub faint">{PLACEHOLDER}</span>
        <button type="button" className={`pill-toggle ${aiOn ? 'on' : ''}`} onClick={toggleAi} disabled={aiBusy || !parser?.key_present} title={parser?.key_present ? 'Gemini reads your messages when on; the built-in reader when off' : 'No Gemini key: the built-in reader is used'} data-testid="ai-toggle">AI reader: {aiOn ? 'on' : 'off'}</button>
        {onHide && !mobile ? <button type="button" className="link hide-link" onClick={onHide} data-testid="hide-chat">hide ▸</button> : null}
        {onHide && mobile ? <button type="button" className="icon" aria-label="close" onClick={onHide} data-testid="chat-sheet-close">✕</button> : null}
        <span className="pill reader-pill" data-testid="reader-pill"><svg className="spk" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2c.6 5.4 4.6 9.4 10 10-5.4.6-9.4 4.6-10 10-.6-5.4-4.6-9.4-10-10 5.4-.6 9.4-4.6 10-10z" fill="currentColor" /></svg>{aiOn ? 'Powered by Gemini' : 'Local parser'}</span>
      </div>
      <div className="log">
        {log.length === 0 ? <div className="msg plain faint">Nothing asked yet. Try "Can I have pizza for dinner?" or tap a button below.</div> : null}
        {log.map((m) => (m.role === 'user' ? <div key={m.id} className="msg user">{m.node}</div> : <div key={m.id} className={m.node?.props?.className === 'msg plain' || m.node?.type === Understood ? '' : 'msg bot'}>{m.node}</div>))}
        <div ref={endRef} />
      </div>
      <QuickLog onAction={onQuick} disabled={busy} parser={parser} />
      <form onSubmit={(e) => { e.preventDefault(); submit() }}>
        <input ref={inputRef} type="text" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); submit() } }} placeholder={PLACEHOLDER} disabled={busy} aria-label="chat message"
               onFocus={() => { if (mobile) setTimeout(() => inputRef.current?.scrollIntoView({ block: 'nearest' }), 250) }} />
        <button type="button" className="icon" aria-label="help" title="Examples and commands" onClick={() => setHelp((x) => !x)}>?</button>
        <button type="submit" className="primary" disabled={busy}>Ask</button>
        {help ? <HelpPopover signature={signature} onPick={(x) => { setHelp(false); setText(x) }} onClose={() => setHelp(false)} /> : null}
      </form>
    </div>
  )
})

export default Chat
