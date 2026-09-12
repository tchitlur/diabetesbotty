import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api, fmtTime, shiftIso, minutesBetween } from '../api.js'
import Status from './Status.jsx'

const ICON = { meal: '🍽', snack: '🍎', workout: '🏃', drink: '🍷', coffee: '☕', insulin: '💉', sleep: '🌙' }
const BAND = { green: '#2f9e5f', amber: '#d68b1c', red: '#d1443f', none: '#e3e5df' }

// Fixed pixel geometry. Nothing here is scaled: x positions are computed in pixels from the measured
// container width, and every element has a fixed pixel size.
export const GEOM = {
  gutter: 80,      // label gutter left of the timeline
  sparkH: 120,     // sparkline height
  gap: 16,         // sparkline → icon row → axis
  icon: 28,        // icon marker diameter
  step: 32,        // icon spacing inside a cluster pill
  axisH: 18,       // axis line + 12 px labels
  bandH: 14,       // band segment height
  bandGap: 6,      // between the two bands (and axis → first band)
  yMin: 40, yMax: 250,
}
const T = {
  spark: 0,
  icons: GEOM.sparkH + GEOM.gap,
  axis: GEOM.sparkH + GEOM.gap + GEOM.icon + GEOM.gap,
}
T.ex = T.axis + GEOM.axisH + GEOM.bandGap
T.gl = T.ex + GEOM.bandH + GEOM.bandGap
T.total = T.gl + GEOM.bandH

// Plan: today at a glance. One headline, one horizontal axis from wake to bedtime, icons above it
// (clustered when close together), a glucose sparkline on top, two bands below. Plain HTML/CSS
// absolute positioning inside a ResizeObserver-measured container; the sparkline is an SVG sized
// in pixels (width = container width, height = 120) with no viewBox.
export default function PlanTab({ version, nowIso, onAccepted }) {
  const [tl, setTl] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [workout, setWorkout] = useState(null)
  const [snacks, setSnacks] = useState([])
  const [tip, setTip] = useState(null)
  const [pick, setPick] = useState(null)
  const [drag, setDrag] = useState(null)
  const [cw, setCw] = useState(0)
  const tlRef = useRef(null)

  const fetchTl = useCallback(async (body) => {
    setBusy(true); setErr(null)
    try { const r = await api.timeline(body); setTl(r); setWorkout(r.workout); setSnacks(r.snacks || []) } catch (e) { setErr(String(e.message)) } finally { setBusy(false) }
  }, [])
  useEffect(() => { fetchTl({ workout, snacks }) }, [version]) // eslint-disable-line react-hooks/exhaustive-deps

  // Measure the timeline container after layout and whenever it resizes.
  const ready = !!tl
  useLayoutEffect(() => {
    const el = tlRef.current
    if (!el) return undefined
    const measure = () => setCw(Math.round(el.getBoundingClientRect().width))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [ready])

  if (!tl && !err) return <div className="card"><Status loading loadingText="Laying out your day…" /></div>
  if (err && !tl) return <div className="card"><Status error={err} /></div>

  const span = Math.max(minutesBetween(tl.start, tl.end), 60)
  const x = (iso) => (Math.min(Math.max(minutesBetween(tl.start, iso), 0), span) / span) * cw
  const xToIso = (px) => { const m = Math.round((px / Math.max(cw, 1)) * span / 30) * 30; return shiftIso(tl.start, Math.min(Math.max(m, 0), span)) }
  const gy = (v) => GEOM.sparkH - ((Math.min(Math.max(v, GEOM.yMin), GEOM.yMax) - GEOM.yMin) / (GEOM.yMax - GEOM.yMin)) * GEOM.sparkH
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

  const tlX = (e) => { const r = tlRef.current.getBoundingClientRect(); return e.clientX - r.left }
  const show = (e, text) => { const r = tlRef.current.getBoundingClientRect(); setTip({ x: e.clientX - r.left, y: e.clientY - r.top, text }) }
  const hide = () => setTip(null)

  // ---- clusters: items within 20 minutes of each other share one pill (pixel units)
  const half = GEOM.icon / 2
  const sorted = [...tl.items].sort((a, b) => (a.time < b.time ? -1 : 1))
  const clusters = []
  for (const it of sorted) {
    const last = clusters[clusters.length - 1]
    if (last && minutesBetween(last.items[last.items.length - 1].time, it.time) <= 20) last.items.push(it)
    else clusters.push({ time: it.time, items: [it] })
  }
  clusters.forEach((c) => {
    c.w = c.items.length > 1 ? GEOM.step * c.items.length + 4 : GEOM.icon
    c.cx = x(c.items[0].time) + (c.items.length > 1 ? (x(c.items[c.items.length - 1].time) - x(c.items[0].time)) / 2 : 0)
  })
  for (let i = 1; i < clusters.length; i++) {           // push pills apart so none overlap
    const a = clusters[i - 1], b = clusters[i]
    const minC = a.cx + a.w / 2 + b.w / 2 + 4
    if (b.cx < minC) b.cx = minC
  }
  for (let i = clusters.length - 1; i >= 0; i--) {      // and keep them inside the axis
    const c = clusters[i]
    if (c.cx + c.w / 2 > cw) c.cx = cw - c.w / 2
    if (c.cx - c.w / 2 < 0) c.cx = c.w / 2
    if (i < clusters.length - 1) { const n = clusters[i + 1]; const maxC = n.cx - n.w / 2 - c.w / 2 - 4; if (c.cx > maxC) c.cx = maxC }
  }
  const dragging = (it) => drag && it.state === 'suggested' && it.kind === 'workout'

  const onPointerDown = (e, it) => {
    if (it.state !== 'suggested' || it.kind !== 'workout') return
    e.currentTarget.setPointerCapture?.(e.pointerId)
    setDrag({ iso: it.time, x: x(it.time) }); setPick(null)
  }
  const onPointerMove = (e) => { if (drag) setDrag((d) => ({ ...d, x: Math.min(Math.max(tlX(e), nowX), cw), moved: true })) }
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

  const bandRow = (cls, rows, top, verb) => (
    <div className={`pt-band ${cls}`} style={{ top, height: GEOM.bandH }} data-testid={`band-${cls}`}>
      {rows.map((b) => {
        const left = x(b.start), width = Math.max(x(b.end) - left, 1)
        return <div key={b.start} className={`pt-seg ${cls}`} style={{ left, width, background: BAND[b.color], opacity: b.past ? 0.4 : 1 }}
                    onMouseMove={(e) => show(e, `${fmtTime(b.start)}: ${b.past && verb ? verb + ' ' : ''}${b.reason}`)} onMouseLeave={hide} />
      })}
    </div>
  )

  return (
    <div className="card plan-card">
      <div className="plan-head">
        <div className="headline">{tl.headline}</div>
        <div className="spacer" />
        <button className="primary" onClick={() => { setPick(null); fetchTl({ auto: true }) }} disabled={busy} title="Places a workout and, if needed, a snack as outlined icons. Solid icons are logged; dashed ones are your usual times; outlined ones are suggestions: tap to accept, drag a workout to move it.">Suggest my day</button>
        <button onClick={() => { setPick(null); fetchTl({}) }} disabled={busy || (!workout && !snacks.length)}>Clear suggestions</button>
      </div>
      <div className="pt-root" style={{ opacity: busy ? 0.6 : 1, height: T.total, paddingLeft: GEOM.gutter }} data-testid="plan-timeline">
        <div className="pt-gutter" style={{ width: GEOM.gutter - 8 }}>
          <span className="pt-lbl" style={{ top: gy(180) - 7 }}>180</span>
          <span className="pt-lbl" style={{ top: gy(70) - 7 }}>70</span>
          <span className="pt-lbl" style={{ top: T.ex }}>exercise</span>
          <span className="pt-lbl" style={{ top: T.gl }}>glucose</span>
        </div>
        <div className="pt-tl" ref={tlRef} style={{ height: T.total }} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={hide} data-testid="timeline">
          {cw > 0 ? <>
            <svg className="pt-spark" width={cw} height={GEOM.sparkH} data-testid="spark">
              <rect x={0} y={gy(180)} width={cw} height={gy(70) - gy(180)} fill="#2f9e5f" opacity="0.08" />
              <path d={seg('actual')} className="pt-actual" data-testid="spark-actual" />
              <path d={seg('forecast')} className="pt-forecast" data-testid="spark-forecast" />
            </svg>
            <div className="pt-now" style={{ left: nowX, height: T.total }} data-testid="now-line" />
            <div className="pt-tick pt-nowtick" style={{ left: nowX - 30, top: 2 }}><span className="pt-lbl pt-nowlbl">now</span></div>

            <div className="pt-icons" style={{ top: T.icons, height: GEOM.icon }}>
              {clusters.map((c, ci) => (
                <React.Fragment key={ci}>
                  {c.items.length > 1 ? <div className="pt-pill" style={{ left: c.cx - c.w / 2, width: c.w, height: GEOM.icon }} /> : null}
                  {c.items.map((it, j) => {
                    const ox = (j - (c.items.length - 1) / 2) * GEOM.step
                    const left = (dragging(it) ? drag.x : c.cx + ox) - half
                    return (
                      <div key={j} className={`pt-item ${it.state} ${it.kind}`} style={{ left, width: GEOM.icon, height: GEOM.icon }} data-kind={it.kind} data-state={it.state} data-time={it.time}
                           onMouseMove={(e) => { e.stopPropagation(); show(e, `${fmtTime(it.time)} · ${it.reason}`) }} onMouseLeave={hide}
                           onPointerDown={(e) => onPointerDown(e, it)} onClick={() => { if (it.state === 'suggested' && it.kind !== 'workout') setPick({ item: it, x: c.cx + ox }) }}>
                        <span className="pt-emoji">{ICON[it.kind] || '•'}</span>
                      </div>
                    )
                  })}
                </React.Fragment>
              ))}
            </div>

            <div className="pt-axis" style={{ top: T.axis, height: GEOM.axisH }} data-testid="axis">
              {labels.map((iso) => <div key={iso} className="pt-tick" style={{ left: x(iso) - 30 }}><i /><span className="pt-lbl pt-axislbl">{fmtTime(iso)}</span></div>)}
            </div>

            {bandRow('ex', tl.exercise_band, T.ex, null)}
            {bandRow('gl', tl.glucose_band, T.gl, 'was')}

            {tip ? <div className="pt-tipwrap" style={{ left: tip.x, top: tip.y - 34 }}><div className="pt-tip">{tip.text}</div></div> : null}
            {pick ? (
              <div className="pt-pickwrap" style={{ left: pick.x, top: T.icons - 84 }}>
                <div className="pt-pick">
                  <div><b>{pick.item.label}</b> at {fmtTime(pick.item.time)}</div>
                  <div className="actions"><button className="small primary" onClick={() => accept(pick.item)}>Add to plan</button><button className="small" onClick={() => dismiss(pick.item)}>Dismiss</button></div>
                </div>
              </div>
            ) : null}
          </> : null}
        </div>
      </div>
      <div className="legend"><span><i className="good" />safe · in range</span><span><i className="warn" />caution · near the edge</span><span><i className="bad" />avoid · out of range</span></div>
    </div>
  )
}
