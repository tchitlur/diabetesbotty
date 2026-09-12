import React from 'react'
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ReferenceLine, ReferenceArea, ResponsiveContainer } from 'recharts'
import { fmtTime } from '../api.js'
import { TICK, TIP, COLORS } from './chart.js'

// A small timeline strip: the next hours with a shaded predicted glucose band, a line for the
// recommended option, and a marker for the proposed action.
export default function Strip({ times, line, p10, p90, markerIso, markerLabel, hours = 6, startIso, height = 120, nowLabel }) {
  if (!times || !times.length) return null
  let a = 0
  if (startIso) { const i = times.findIndex((t) => t >= startIso); a = i < 0 ? 0 : i }
  const n = Math.min(times.length - a, hours * 12 + 1)
  const data = []
  for (let i = a; i < a + n; i++) {
    if (data.length && data[data.length - 1].iso === times[i]) continue   // a repeated boundary point would give Recharts two ticks with one key
    data.push({ t: fmtTime(times[i]), iso: times[i], line: line?.[i], p10: p10?.[i], band: p90 && p10 ? p90[i] - p10[i] : undefined })
  }
  const m = markerIso ? data.find((d) => d.iso >= markerIso.slice(0, 16)) : null
  const mIdx = m ? data.indexOf(m) : -1
  const ticks = data.filter((d) => d.iso.slice(14, 16) === '00').map((d) => d.t)
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ left: 0, right: 10, top: 14, bottom: 0 }}>
        <XAxis dataKey="t" tick={TICK} ticks={ticks} interval={0} />
        <YAxis domain={[40, 300]} tick={TICK} width={36} ticks={[70, 180]} />
        <Tooltip contentStyle={TIP} formatter={(v, nme) => (nme === 'likely range' ? [null, null] : [`${Math.round(v)} mg/dL`, nme])} labelFormatter={(l) => `at ${l}`} />
        <ReferenceArea y1={70} y2={180} fill={COLORS.range} fillOpacity={0.07} />
        <ReferenceLine y={70} stroke={COLORS.bad} strokeDasharray="3 3" />
        {m ? <ReferenceLine x={m.t} stroke={COLORS.accent} strokeWidth={2} label={{ value: markerLabel || 'proposed', position: mIdx < data.length / 2 ? 'insideTopLeft' : 'insideTopRight', fontSize: 11, fill: COLORS.accent }} /> : null}
        {nowLabel ? <ReferenceLine x={nowLabel} stroke={COLORS.s4} strokeDasharray="2 2" /> : null}
        <Area type="monotone" dataKey="p10" stackId="b" stroke="none" fill="transparent" isAnimationActive={false} legendType="none" tooltipType="none" />
        <Area type="monotone" dataKey="band" stackId="b" stroke="none" fill={COLORS.accent} fillOpacity={0.15} isAnimationActive={false} name="likely range" />
        <Line type="monotone" dataKey="line" stroke={COLORS.accent} dot={false} strokeWidth={2} isAnimationActive={false} name="expected" />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
