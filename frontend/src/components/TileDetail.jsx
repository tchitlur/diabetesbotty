import React from 'react'
import { ComposedChart, Line, BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ReferenceArea, ReferenceLine, ResponsiveContainer, CartesianGrid } from 'recharts'
import { fmtTime, fmtDate, minutesBetween } from '../api.js'
import { TICK, TIP, GRID, COLORS } from './chart.js'

// The view under a tapped tile. Fast quantities: last 3 h (model estimate) + next 3 h forecast on a
// fixed axis. Slow quantities: the last 7 days as bars, today highlighted, the normal zone shaded.
export default function TileDetail({ tile, nowIso, onClose }) {
  const d = tile.detail
  if (!d) return null
  const [y0, y1] = d.y
  const unit = (tile.unit || '').replace('/ ', 'out of ')
  return (
    <div className="card tile-detail">
      <div className="tile-detail-head"><span>{tile.icon} <b>{tile.label}</b> · {d.kind === 'fast' ? 'last 3 hours and next 3 hours' : 'last 7 days'}</span><button className="small ghost" onClick={onClose}>close</button></div>
      <div className="sentence">{d.sentence}</div>
      {d.kind === 'fast' ? <FastChart d={d} y0={y0} y1={y1} unit={unit} nowIso={nowIso} label={tile.label} /> : <SlowChart d={d} y0={y0} y1={y1} unit={unit} label={tile.label} />}
    </div>
  )
}

function FastChart({ d, y0, y1, unit, nowIso, label }) {
  const t0 = d.past.times[0]
  const rows = []
  d.past.times.forEach((t, i) => rows.push({ m: minutesBetween(t0, t), iso: t, past: d.past.values[i] }))
  d.forecast.times.forEach((t, i) => { const m = minutesBetween(t0, t); if (i === 0 && rows.length && Math.abs(rows[rows.length - 1].m - m) < 1) rows[rows.length - 1].next = d.forecast.values[0]; else rows.push({ m, iso: t, next: d.forecast.values[i] }) })
  const ticks = rows.filter((r) => r.iso.slice(14, 16) === '00').map((r) => r.m)
  const nowM = nowIso ? minutesBetween(t0, nowIso) : null
  return (
    <ResponsiveContainer width="100%" height={150}>
      <ComposedChart data={rows} margin={{ left: 0, right: 34, top: 14, bottom: 0 }}>
        <CartesianGrid {...GRID} vertical={false} />
        <XAxis dataKey="m" type="number" domain={['dataMin', 'dataMax']} ticks={ticks} tick={TICK} tickFormatter={(m) => fmtTime(rows.find((r) => Math.abs(r.m - m) < 0.5)?.iso || '')} />
        <YAxis domain={[y0, y1]} tick={TICK} width={44} allowDataOverflow />
        <Tooltip contentStyle={TIP} formatter={(v, n) => [`${v} ${unit}`.trim(), n]} labelFormatter={(m) => `at ${fmtTime(rows.find((r) => Math.abs(r.m - m) < 0.5)?.iso || '')}`} />
        {d.zones.map((z) => <ReferenceArea key={z.label} y1={z.from} y2={z.to} fill={COLORS.range} fillOpacity={0.1} label={{ value: z.label, position: 'insideTopRight', fontSize: 11, fill: COLORS.s4 }} />)}
        {nowM != null ? <ReferenceLine x={nowM} stroke={COLORS.s4} strokeDasharray="3 3" label={{ value: 'now', position: 'top', fontSize: 11, fill: COLORS.s4 }} /> : null}
        <Line type="monotone" dataKey="past" stroke={COLORS.cgm} dot={false} strokeWidth={2} isAnimationActive={false} name={`${label} (estimated)`} connectNulls={false} />
        <Line type="monotone" dataKey="next" stroke={COLORS.accent} strokeOpacity={0.7} dot={false} strokeWidth={1.6} strokeDasharray="5 4" isAnimationActive={false} name={`${label} (forecast)`} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

function SlowChart({ d, y0, y1, unit, label }) {
  const rows = d.days.map((r) => ({ ...r, d: fmtDate(r.date).replace(/,.*/, '') + (r.today ? ' (today)' : '') }))
  return (
    <ResponsiveContainer width="100%" height={150}>
      <BarChart data={rows} margin={{ left: 0, right: 34, top: 14, bottom: 0 }}>
        <CartesianGrid {...GRID} vertical={false} />
        <XAxis dataKey="d" tick={TICK} interval={0} />
        <YAxis domain={[y0, y1]} tick={TICK} width={44} allowDataOverflow />
        <Tooltip contentStyle={TIP} formatter={(v) => [`${v} ${unit}`.trim(), label]} labelFormatter={(l) => l} />
        {d.zones.map((z) => <ReferenceArea key={z.label} y1={z.from} y2={z.to} fill={z.label === 'check' ? COLORS.bad : COLORS.range} fillOpacity={0.1} label={{ value: z.label, position: 'insideTopRight', fontSize: 11, fill: COLORS.s4 }} />)}
        <Bar dataKey="value" isAnimationActive={false} name={label} radius={[4, 4, 0, 0]}>
          {rows.map((r) => <Cell key={r.date} fill={r.today ? COLORS.accent : '#c9d3cf'} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
