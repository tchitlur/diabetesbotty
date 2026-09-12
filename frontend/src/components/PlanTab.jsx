import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, fmtTime, shiftIso, minutesBetween } from '../api.js'
import Status from './Status.jsx'

const ICON = { meal: '🍽', snack: '🍎', workout: '🏃', drink: '🍷', coffee: '☕', insulin: '💉', sleep: '🌙' }
const BAND = { green: '#2f9e5f', amber: '#d68b1c', red: '#d1443f', none: '#e3e5df' }
const W = 1000, PAD_L = 52, PAD_R = 20
const Y = { spark: [14, 88], icons: 116, axis: 146, ex: [160, 170], gl: [178, 188] }
const R = 9            // icon radius (about half the old size)
const STEP = 19        // icon spacing inside a cluster pill

// Plan: today at a glance. One headline, one horizontal axis from wake to bedtime, icons above it
// (clustered when close together), a glucose sparkline on top, two thin bands below.
export default function PlanTab({ version, nowIso, onAccepted }) {
  const [tl, setTl] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [workout, setWorkout] = useState(null)
  const [snacks, setSnacks] = useState([])
  const [tip, setTip] = useState(null)
  const [pick, setPick] = useState(null)
  const [drag, setDrag] = useState(null)
  const svgRef = useRef(null)

  const fetchTl = useCallback(async (body) => {
    setBusy(true); setErr(null)
    try { const r = await api.timeline(body); setTl(r); setWorkout(r.workout); setSnacks(r.snacks || []) } catch (e) { setErr(String(e.message)) } finally { setBusy(false) }
  }, [])
  useEffect(() => { fetchTl({ workout, snacks }) }, [version]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!tl && !err) return <div className="card"><Status loading loadingText="Laying out your day…" /></div>
  if (err && !tl) return <div className="card"><Status error={err} /></div>

  const span = Math.max(minutesBetween(tl.start, tl.end), 60)
  const x = (iso) => PAD_L + (Math.min(Math.max(minutesBetween(tl.start, iso), 0), span) / span) * (W - PAD_L - PAD_R)
  const xToIso = (px) => { const m = Math.round(((px - PAD_L) / (W - PAD_L - PAD_R)) * span / 30) * 30; return shiftIso(tl.start, Math.min(Math.max(m, 0), span)) }
  const gy = (v) => Y.spark[1] - ((Math.min(Math.max(v, 40), 300) - 40) / 260) * (Y.spark[1] - Y.spark[0])
  const nowX = x(tl.now)

  const seg = (kind) => {
    let d = '', pen = false
    tl.sparkline.times.forEach((t, i) => {
      const v = tl.sparkline.values[i], k = tl.sparkline.kind[i]
      const inc = k === kind || (kind === 'forecast' && i > 0 && tl.sparkline.kind[i - 1] === 'actual' && k === 'forecast')
      if (v == null || !inc) { pen = false; return }
      d += `${pen ? 'L' : 'M'}${x(t).toFixed(1)},${gy(v).toFixed(1)} `; pen = true
    })
    return d
  }
  const labels = []
  for (let m = 0; m <= span; m += 5) {
    const iso = shiftIso(tl.start, m)
    if (Number(iso.slice(14, 16)) === 0 && Number(iso.slice(11, 13)) % 2 === 0) labels.push(iso)
  }

  const show = (e, text) => { const r = svgRef.current.getBoundingClientRect(); setTip({ x: e.clientX - r.left, y: e.clientY - r.top, text }) }
  const hide = () => setTip(null)
  const svgX = (e) => { const r = svgRef.current.getBoundingClientRect(); return ((e.clientX - r.left) / r.width) * W }

  // ---- clusters: items within 20 minutes of each other share one pill
  const sorted = [...tl.items].sort((a, b) => (a.time < b.time ? -1 : 1))
  const clusters = []
  for (const it of sorted) {
    const last = clusters[clusters.length - 1]
    if (last && minutesBetween(last.items[last.items.length - 1].time, it.time) <= 20) last.items.push(it)
    else clusters.push({ time: it.time, items: [it] })
  }
  clusters.forEach((c) => { c.w = STEP * c.items.length + 6; c.cx = x(c.items[0].time) + (c.items.length > 1 ? (x(c.items[c.items.length - 1].time) - x(c.items[0].time)) / 2 : 0) })
  for (let i = 1; i < clusters.length; i++) {           // push pills apart so none overlap
    const a = clusters[i - 1], b = clusters[i]
    const minC = a.cx + a.w / 2 + b.w / 2 + 3
    if (b.cx < minC) b.cx = minC
  }
  for (let i = clusters.length - 1; i >= 0; i--) {      // and keep them inside the axis
    const c = clusters[i]
    if (c.cx + c.w / 2 > W - PAD_R) c.cx = W - PAD_R - c.w / 2
    if (i < clusters.length - 1) { const n = clusters[i + 1]; const maxC = n.cx - n.w / 2 - c.w / 2 - 3; if (c.cx > maxC) c.cx = maxC }
  }
  const dragging = (it) => drag && it.state === 'suggested' && it.kind === 'workout'

  const onPointerDown = (e, it) => {
    if (it.state !== 'suggested' || it.kind !== 'workout') return
    e.currentTarget.setPointerCapture?.(e.pointerId)
    setDrag({ iso: it.time, x: x(it.time) }); setPick(null)
  }
  const onPointerMove = (e) => { if (drag) setDrag((d) => ({ ...d, x: Math.min(Math.max(svgX(e), nowX), W - PAD_R), moved: true })) }
  const onPointerUp = () => {
    if (!drag) return
    const d = drag; setDrag(null)
    if (d.moved) { const iso = xToIso(d.x); if (iso !== workout?.start) fetchTl({ workout: { ...workout, start: iso }, snacks }) }
    else { const it = tl.items.find((i) => i.state === 'suggested' && i.kind === 'workout'); if (it) setPick({ item: it, x: d.x }) }
  }
  const accept = async (it) => {
    setPick(null)
    try {
      await api.accept([it.event])
      const rest = it.kind === 'workout' ? snacks : snacks.filter((s) => s !== it.time)
      onAccepted && onAccepted()
      await fetchTl({ workout: it.kind === 'workout' ? null : workout, snacks: rest })
    } catch (e) { setErr(String(e.message)) }
  }
  const dismiss = (it) => { setPick(null); fetchTl({ workout: it.kind === 'workout' ? null : workout, snacks: it.kind === 'workout' ? snacks : snacks.filter((s) => s !== it.time) }) }

  return (
    <div className="card plan-card">
      <div className="plan-head">
        <div className="headline">{tl.headline}</div>
        <div className="spacer" />
        <button className="primary" onClick={() => { setPick(null); fetchTl({ auto: true }) }} disabled={busy} title="Places a workout and, if needed, a snack as outlined icons. Solid icons are logged; dashed ones are your usual times; outlined ones are suggestions: tap to accept, drag a workout to move it.">Suggest my day</button>
        <button onClick={() => { setPick(null); fetchTl({}) }} disabled={busy || (!workout && !snacks.length)}>Clear suggestions</button>
      </div>
      <div className="pt-wrap" style={{ opacity: busy ? 0.6 : 1 }}>
        <svg ref={svgRef} className="pt" viewBox={`0 0 ${W} 200`} preserveAspectRatio="none" onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={hide}>
          <defs><clipPath id="pt-clip"><rect x={PAD_L} y={Y.spark[0]} width={W - PAD_L - PAD_R} height={Y.spark[1] - Y.spark[0]} /></clipPath></defs>
          <rect x={PAD_L} y={gy(180)} width={W - PAD_L - PAD_R} height={gy(70) - gy(180)} fill="#2f9e5f" opacity="0.08" />
          <text x={PAD_L - 6} y={gy(180) + 4} className="pt-lbl" textAnchor="end">180</text>
          <text x={PAD_L - 6} y={gy(70) + 4} className="pt-lbl" textAnchor="end">70</text>
          <g clipPath="url(#pt-clip)"><path d={seg('actual')} className="pt-actual" data-testid="spark-actual" /><path d={seg('forecast')} className="pt-forecast" data-testid="spark-forecast" /></g>
          <line x1={nowX} x2={nowX} y1={Y.spark[0]} y2={Y.gl[1]} className="pt-now" />
          <text x={nowX} y={Y.spark[0] - 3} className="pt-lbl pt-nowlbl" textAnchor="middle">now</text>
          <line x1={PAD_L} x2={W - PAD_R} y1={Y.axis} y2={Y.axis} className="pt-axis" />
          {labels.map((iso) => <g key={iso}><line x1={x(iso)} x2={x(iso)} y1={Y.axis} y2={Y.axis + 4} className="pt-axis" /><text x={x(iso)} y={Y.axis + 15} className="pt-lbl" textAnchor="middle">{fmtTime(iso)}</text></g>)}
          <text x={PAD_L - 6} y={Y.ex[1] - 1} className="pt-lbl" textAnchor="end">exercise</text>
          {tl.exercise_band.map((b) => <rect key={b.start} className="pt-seg ex" x={x(b.start)} y={Y.ex[0]} width={Math.max(x(b.end) - x(b.start) - 1, 0.5)} height={Y.ex[1] - Y.ex[0]} fill={BAND[b.color]} opacity={b.past ? 0.4 : 1} rx="2" onMouseMove={(e) => show(e, `${fmtTime(b.start)}: ${b.reason}`)} onMouseLeave={hide} />)}
          <text x={PAD_L - 6} y={Y.gl[1] - 1} className="pt-lbl" textAnchor="end">glucose</text>
          {tl.glucose_band.map((b) => <rect key={b.start} className="pt-seg gl" x={x(b.start)} y={Y.gl[0]} width={Math.max(x(b.end) - x(b.start) - 1, 0.5)} height={Y.gl[1] - Y.gl[0]} fill={BAND[b.color]} opacity={b.past ? 0.4 : 1} rx="2" onMouseMove={(e) => show(e, `${fmtTime(b.start)}: ${b.past ? 'was ' : 'expected '}${b.reason}`)} onMouseLeave={hide} />)}
          {clusters.map((c, ci) => (
            <g key={ci} className="pt-cluster" transform={`translate(${c.cx},${Y.icons})`}>
              <line x1="0" x2="0" y1={R + 2} y2={Y.axis - Y.icons} className="pt-stem" />
              {c.items.length > 1 ? <rect x={-c.w / 2} y={-R - 3} width={c.w} height={2 * R + 6} rx={R + 3} className="pt-pill" /> : null}
              {c.items.map((it, j) => {
                const ox = (j - (c.items.length - 1) / 2) * STEP
                const px = dragging(it) ? drag.x - c.cx : ox
                return (
                  <g key={j} className={`pt-item ${it.state} ${it.kind}`} transform={`translate(${px},0)`} data-kind={it.kind} data-state={it.state} data-time={it.time}
                     onMouseMove={(e) => { e.stopPropagation(); show(e, `${fmtTime(it.time)} · ${it.reason}`) }} onMouseLeave={hide}
                     onPointerDown={(e) => onPointerDown(e, it)} onClick={() => { if (it.state === 'suggested' && it.kind !== 'workout') setPick({ item: it, x: c.cx + ox }) }}>
                    <circle r={R} className="pt-dot" />
                    <text y="3" textAnchor="middle" className="pt-emoji">{ICON[it.kind] || '•'}</text>
                  </g>
                )
              })}
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
      <div className="legend"><span><i className="good" />safe · in range</span><span><i className="warn" />caution · near the edge</span><span><i className="bad" />avoid · out of range</span></div>
    </div>
  )
}
