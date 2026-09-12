import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, fmtTime, shiftIso } from '../api.js'
import Status from './Status.jsx'

const ICON = { meal: '🍽', snack: '🍎', workout: '🏃', drink: '🍷', coffee: '☕', insulin: '💉', wake: '☀️', sleep: '🌙' }
const BAND = { green: '#2f9e5f', amber: '#d68b1c', red: '#d1443f', none: '#e3e5df' }
const W = 1000, PAD_L = 56, PAD_R = 24
const Y = { spark: [14, 92], icons: 128, axis: 168, ex: [186, 198], gl: [208, 220] }

const toMin = (iso) => { const d = new Date(iso); return d.getHours() * 60 + d.getMinutes() + (d.getDate() !== new Date(iso.slice(0, 10) + 'T00:00').getDate() ? 0 : 0) }
// The whole day lives on one axis: minutes since the window start (handles a bedtime after midnight).
const minutesSince = (iso, startIso) => (new Date(iso) - new Date(startIso)) / 60000

// Plan: today at a glance. One headline, one horizontal axis from wake to bedtime, icons above it,
// a glucose sparkline on top, two thin bands below (exercise safety, predicted glucose).
export default function PlanTab({ version, nowIso, onAccepted }) {
  const [tl, setTl] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [workout, setWorkout] = useState(null)
  const [snacks, setSnacks] = useState([])
  const [tip, setTip] = useState(null)        // { x, y, text }
  const [pick, setPick] = useState(null)      // a suggested item awaiting accept / dismiss
  const [drag, setDrag] = useState(null)      // { startX, iso, x }
  const svgRef = useRef(null)

  const fetchTl = useCallback(async (body) => {
    setBusy(true); setErr(null)
    try {
      const r = await api.timeline(body)
      setTl(r); setWorkout(r.workout); setSnacks(r.snacks || [])
    } catch (e) { setErr(String(e.message)) } finally { setBusy(false) }
  }, [])
  useEffect(() => { fetchTl({ workout, snacks }) }, [version]) // eslint-disable-line react-hooks/exhaustive-deps

  const suggest = () => { setPick(null); fetchTl({ auto: true }) }
  const clear = () => { setPick(null); fetchTl({}) }

  if (!tl && !err) return <div className="card"><Status loading loadingText="Laying out your day…" /></div>
  if (err && !tl) return <div className="card"><Status error={err} /></div>

  const span = Math.max(minutesSince(tl.end, tl.start), 60)
  const x = (iso) => PAD_L + (Math.min(Math.max(minutesSince(iso, tl.start), 0), span) / span) * (W - PAD_L - PAD_R)
  const xToIso = (px) => { const m = Math.round(((px - PAD_L) / (W - PAD_L - PAD_R)) * span / 30) * 30; return shiftIso(tl.start, Math.min(Math.max(m, 0), span)) }
  const gy = (v) => Y.spark[1] - ((Math.min(Math.max(v, 40), 300) - 40) / 260) * (Y.spark[1] - Y.spark[0])
  const nowX = x(tl.now)

  // sparkline paths: actual (solid) and forecast (dashed, lighter); breaks at nulls
  const seg = (kind) => {
    let d = '', pen = false
    tl.sparkline.times.forEach((t, i) => {
      const v = tl.sparkline.values[i]
      const k = tl.sparkline.kind[i]
      const inc = k === kind || (kind === 'forecast' && i > 0 && tl.sparkline.kind[i - 1] === 'actual' && k === 'forecast')
      if (v == null || !inc) { pen = false; return }
      d += `${pen ? 'L' : 'M'}${x(t).toFixed(1)},${gy(v).toFixed(1)} `; pen = true
    })
    return d
  }
  // axis labels every 2 h from the first even hour
  const labels = []
  for (let m = 0; m <= span; m += 5) {
    const iso = shiftIso(tl.start, m)
    const hh = Number(iso.slice(11, 13)), mm = Number(iso.slice(14, 16))
    if (mm === 0 && hh % 2 === 0) labels.push(iso)
  }

  const show = (e, text) => { const r = svgRef.current.getBoundingClientRect(); setTip({ x: e.clientX - r.left, y: e.clientY - r.top, text }) }
  const hide = () => setTip(null)

  // drag a suggested workout: move it, then recompute the bands
  const onPointerDown = (e, it) => {
    if (it.state !== 'suggested' || it.kind !== 'workout') return
    e.currentTarget.setPointerCapture?.(e.pointerId)
    setDrag({ pointerId: e.pointerId, iso: it.time, x: x(it.time) })
    setPick(null)
  }
  const svgX = (e) => { const r = svgRef.current.getBoundingClientRect(); return ((e.clientX - r.left) / r.width) * W }
  const onPointerMove = (e) => { if (drag) setDrag((d) => ({ ...d, x: Math.min(Math.max(svgX(e), x(tl.now)), W - PAD_R), moved: true })) }
  const onPointerUp = (e) => {
    if (!drag) return
    const d = drag; setDrag(null)
    if (d.moved) {
      const iso = xToIso(d.x)
      if (iso !== workout?.start) fetchTl({ workout: { ...workout, start: iso }, snacks })
    } else {
      const it = tl.items.find((i) => i.state === 'suggested' && i.kind === 'workout')
      if (it) setPick({ item: it, x: d.x })
    }
  }
  const accept = async (it) => {
    setPick(null)
    try {
      await api.accept([it.event])
      if (it.kind === 'workout') setWorkout(null)
      const rest = it.kind === 'workout' ? snacks : snacks.filter((s) => s !== it.time)
      if (it.kind !== 'workout') setSnacks(rest)
      onAccepted && onAccepted()   // bumps version -> refetch with the item now logged
      await fetchTl({ workout: it.kind === 'workout' ? null : workout, snacks: rest })
    } catch (e) { setErr(String(e.message)) }
  }
  const dismiss = (it) => {
    setPick(null)
    const rest = it.kind === 'workout' ? snacks : snacks.filter((s) => s !== it.time)
    fetchTl({ workout: it.kind === 'workout' ? null : workout, snacks: rest })
  }

  // stack icons that share a slot
  const placed = []
  const items = tl.items.map((it) => {
    const px = drag && it.state === 'suggested' && it.kind === 'workout' ? drag.x : x(it.time)
    const lvl = placed.filter((p) => Math.abs(p - px) < 22).length
    placed.push(px)
    return { ...it, px, py: Y.icons - lvl * 26 }
  })

  return (
    <>
      <div className="card plan-card">
        <div className="plan-head">
          <div className="headline">{tl.headline}</div>
          <div className="spacer" />
          <button className="primary" onClick={suggest} disabled={busy}>Suggest my day</button>
          <button onClick={clear} disabled={busy || (!workout && !snacks.length)}>Clear suggestions</button>
        </div>
        <div className="pt-wrap" style={{ opacity: busy ? 0.6 : 1 }}>
          <svg ref={svgRef} className="pt" viewBox={`0 0 ${W} 232`} preserveAspectRatio="none" onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={hide}>
            {/* target range + sparkline */}
            <rect x={PAD_L} y={gy(180)} width={W - PAD_L - PAD_R} height={gy(70) - gy(180)} fill="#2f9e5f" opacity="0.08" />
            <text x={PAD_L - 6} y={gy(180) + 4} className="pt-lbl" textAnchor="end">180</text>
            <text x={PAD_L - 6} y={gy(70) + 4} className="pt-lbl" textAnchor="end">70</text>
            <path d={seg('actual')} className="pt-actual" />
            <path d={seg('forecast')} className="pt-forecast" />
            {/* now */}
            <line x1={nowX} x2={nowX} y1={Y.spark[0]} y2={Y.gl[1]} className="pt-now" />
            <text x={nowX} y={Y.spark[0] - 3} className="pt-lbl pt-nowlbl" textAnchor="middle">now</text>
            {/* axis */}
            <line x1={PAD_L} x2={W - PAD_R} y1={Y.axis} y2={Y.axis} className="pt-axis" />
            {labels.map((iso) => <g key={iso}><line x1={x(iso)} x2={x(iso)} y1={Y.axis} y2={Y.axis + 5} className="pt-axis" /><text x={x(iso)} y={Y.axis + 17} className="pt-lbl" textAnchor="middle">{fmtTime(iso)}</text></g>)}
            {/* bands */}
            <text x={PAD_L - 6} y={Y.ex[1] - 2} className="pt-lbl" textAnchor="end">exercise</text>
            {tl.exercise_band.map((b) => <rect key={b.start} className="pt-seg" x={x(b.start)} y={Y.ex[0]} width={Math.max(x(b.end) - x(b.start) - 1, 1)} height={Y.ex[1] - Y.ex[0]} fill={BAND[b.color]} rx="2" onMouseMove={(e) => show(e, `${fmtTime(b.start)}: ${b.reason}`)} onMouseLeave={hide} />)}
            {tl.exercise_band.length === 0 ? <text x={PAD_L + 4} y={Y.ex[1] - 2} className="pt-lbl">no time left today</text> : null}
            <text x={PAD_L - 6} y={Y.gl[1] - 2} className="pt-lbl" textAnchor="end">glucose</text>
            {tl.glucose_band.map((b) => <rect key={b.start} className="pt-seg" x={x(b.start)} y={Y.gl[0]} width={Math.max(x(b.end) - x(b.start) - 1, 1)} height={Y.gl[1] - Y.gl[0]} fill={BAND[b.color]} opacity={b.past ? 0.55 : 1} rx="2" onMouseMove={(e) => show(e, `${fmtTime(b.start)}: ${b.past ? 'was ' : 'expected '}${b.reason}`)} onMouseLeave={hide} />)}
            {/* icons */}
            {items.map((it, i) => (
              <g key={i} className={`pt-item ${it.state} ${it.kind}`} transform={`translate(${it.px},${it.py})`} data-kind={it.kind} data-state={it.state} data-time={it.time}
                 onMouseMove={(e) => show(e, `${fmtTime(it.time)} · ${it.reason}`)} onMouseLeave={hide}
                 onPointerDown={(e) => onPointerDown(e, it)}
                 onClick={(e) => { if (it.state === 'suggested' && it.kind !== 'workout') setPick({ item: it, x: it.px }) }}>
                <line x1="0" x2="0" y1="14" y2={Y.axis - it.py} className="pt-stem" />
                <circle r="14" className="pt-dot" />
                <text y="5" textAnchor="middle" className="pt-emoji">{ICON[it.kind] || '•'}</text>
              </g>
            ))}
          </svg>
          {tip ? <div className="pt-tip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div> : null}
          {pick ? (
            <div className="pt-pick" style={{ left: `${(pick.x / W) * 100}%` }}>
              <div><b>{pick.item.label}</b> at {fmtTime(pick.item.time)}</div>
              <div className="actions"><button className="small primary" onClick={() => accept(pick.item)}>Add to plan</button><button className="small" onClick={() => dismiss(pick.item)}>Dismiss</button></div>
            </div>
          ) : null}
        </div>
        <div className="legend">
          <span><i className="good" />safe to exercise / in range</span><span><i className="warn" />caution / near the edge</span><span><i className="bad" />avoid / out of range</span>
          <span className="faint">solid icon = logged · dashed = your usual · outlined = suggested (tap to accept, drag a workout to move it)</span>
        </div>
      </div>
    </>
  )
}
