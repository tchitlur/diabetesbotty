import React, { useCallback, useEffect, useState } from 'react'
import { api, fmtTime } from '../api.js'
import Status from './Status.jsx'

const ICON = { meal: '🍽', snack: '🍎', workout: '🏃', drink: '🍷', coffee: '☕', sleep: '🌙' }

// Plan: one vertical timeline from now until bedtime. Bands say when exercise is safe (green),
// needs care (amber) or is better avoided (red). Tap a workout, then a time, to move it.
export default function PlanTab({ version, nowIso }) {
  const [tl, setTl] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [workout, setWorkout] = useState(null)   // the planned (movable) workout
  const [snack, setSnack] = useState(null)
  const [moving, setMoving] = useState(false)
  const [why, setWhy] = useState(null)          // slot start whose reason is shown

  const fetchTl = useCallback(async (body) => {
    setBusy(true); setErr(null)
    try {
      const r = await api.timeline(body)
      setTl(r); setWorkout(r.workout); setSnack(r.snack)
    } catch (e) { setErr(String(e.message)) } finally { setBusy(false) }
  }, [])

  useEffect(() => { fetchTl({ workout, snack }) }, [version]) // eslint-disable-line react-hooks/exhaustive-deps

  const planMyDay = () => fetchTl({ auto: true })
  const clear = () => { setMoving(false); fetchTl({}) }
  const moveTo = (start) => { setMoving(false); fetchTl({ workout: { ...workout, start }, snack }) }

  const slotOf = (iso) => tl.slots.find((s) => iso >= s.start && iso < s.end)
  const rows = []
  if (tl) {
    let lastDay = ''
    let first = true
    for (const s of tl.slots) {
      const day = s.start.slice(0, 10)
      if (day !== lastDay) { rows.push({ kind: 'day', key: `d${day}`, label: tl.days.find((d) => d.date === day)?.label || day }); lastDay = day }
      if (first) { rows.push({ kind: 'now', key: 'now' }); first = false }
      const items = tl.items.filter((it) => slotOf(it.time)?.start === s.start)
      rows.push({ kind: 'slot', key: s.start, slot: s, items })
    }
    // items after the last slot (bedtime) land in a trailing row
    const tail = tl.items.filter((it) => !slotOf(it.time))
    if (tail.length) rows.push({ kind: 'slot', key: 'tail', slot: { start: tl.end, end: tl.end, color: 'none', reason: '' }, items: tail })
  }

  return (
    <>
      <div className="card">
        <div className="plan-head">
          <button className="primary" onClick={planMyDay} disabled={busy}>Plan my day</button>
          <button onClick={clear} disabled={busy}>Clear</button>
          <span className="hint">{moving ? 'Now tap a time to move the workout there.' : workout ? 'Tap the workout to move it.' : 'Green: good time to exercise. Amber: take care. Red: better not. Tap an amber or red band to see why.'}</span>
        </div>
        <div className="legend" style={{ marginTop: 8 }}><span><i className="good" />safe to exercise</span><span><i className="warn" />caution</span><span><i className="bad" />avoid</span><span className="faint">dashed = predicted from your usual days · solid = logged or planned</span></div>
      </div>
      <div className="card">
        <Status loading={!tl && busy} error={err} loadingText="Checking every half hour until bedtime…">
          {tl ? (
            <div className="tl" style={{ opacity: busy ? 0.6 : 1 }}>
              {rows.map((r) => {
                if (r.kind === 'day') return <div key={r.key} className="day">{r.label}</div>
                if (r.kind === 'now') return <div key={r.key} className="now">now · {fmtTime(tl.start)}</div>
                const s = r.slot
                const onTheHour = s.start.slice(14, 16) === '00'
                const clickable = moving || (s.color !== 'green' && s.color !== 'none' && s.reason)
                return (
                  <React.Fragment key={r.key}>
                    <div className="t">{onTheHour || r.key === 'tail' ? fmtTime(s.start) : ''}</div>
                    <div className={`slot ${s.color} ${moving ? 'drop' : ''}`} data-start={s.start} role={clickable ? 'button' : undefined}
                         onClick={() => { if (moving) moveTo(s.start); else if (s.reason) setWhy(why === s.start ? null : s.start) }}
                         title={s.reason ? `${fmtTime(s.start)}: ${s.reason}` : ''}>
                      {r.items.map((it, i) => (
                        <span key={i} className={`item ${it.predicted ? 'predicted' : ''} ${it.movable ? 'movable' : ''} ${it.movable && moving ? 'selected' : ''}`}
                              onClick={(e) => { if (it.movable) { e.stopPropagation(); setMoving((m) => !m) } }} role={it.movable ? 'button' : undefined}>
                          {ICON[it.kind] || '•'} {it.label}{it.kind === 'meal' || it.kind === 'sleep' ? '' : ''} <span className="faint">{fmtTime(it.time)}</span>
                        </span>
                      ))}
                    </div>
                    {why === s.start && s.reason ? <div className="why">{s.reason[0].toUpperCase() + s.reason.slice(1)}.</div> : null}
                  </React.Fragment>
                )
              })}
            </div>
          ) : null}
        </Status>
      </div>
    </>
  )
}
