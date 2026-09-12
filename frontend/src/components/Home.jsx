import React, { useState } from 'react'
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ReferenceLine, ReferenceArea, ResponsiveContainer, CartesianGrid } from 'recharts'
import { LineChart } from 'recharts'
import { fmtTime, fmtRel } from '../api.js'
import Status, { ChartBox } from './Status.jsx'
import Tile from './Tile.jsx'
import { TICK, TIP, GRID, COLORS } from './chart.js'

// Display-only smoothing: a 3-point moving average that leaves gaps (nulls) alone.
function smooth3(arr) {
  return arr.map((v, i) => {
    if (v == null) return null
    const a = arr[i - 1], b = arr[i + 1]
    if (a == null || b == null) return v
    return (a + v + b) / 3
  })
}

// Build the one display series: sensor (now-3h .. now, short gaps already interpolated by the
// backend, long gaps kept as breaks) followed by the forecast anchored on the last sensor point.
function buildSeries(h) {
  const actual = smooth3(h.history.display)
  const rows = h.history.times.map((t, i) => ({ t: fmtTime(t), iso: t, actual: actual[i] == null ? null : Math.round(actual[i] * 10) / 10 }))
  const lastIdx = rows.map((r) => r.actual).lastIndexOf(null) === rows.length - 1 ? -1 : rows.length - 1
  const last = lastIdx >= 0 ? rows[lastIdx].actual : null
  const f = h.forecast
  const offset = last != null ? last - f.median[0] : 0   // the model's estimate vs the sensor: blend the difference away over the first hour
  f.times.forEach((t, i) => {
    const w = Math.max(0, 1 - i / 12)
    const row = { t: fmtTime(t), iso: t, median: f.median[i] + offset * w, p10: f.p10[i] + offset * w, band: f.p90[i] - f.p10[i] }
    if (i === 0 && rows.length && rows[rows.length - 1].iso === t) Object.assign(rows[rows.length - 1], row)
    else rows.push(row)
  })
  return rows
}

// Home: one big glucose number, one chart, the "right now" tiles, the "coming up" cards.
export default function Home({ home, nowIso }) {
  const [open, setOpen] = useState(null)
  const h = home.data
  const g = h?.glucose
  const data = h ? buildSeries(h) : []
  const nowLabel = h ? fmtTime(h.as_of) : ''
  const hourTicks = data.filter((d) => d.t.endsWith(':00')).map((d) => d.t)
  const gaps = h?.history?.gaps || []
  const tile = h && open ? h.tiles.find((t) => t.key === open) : null
  return (
    <>
      <div className="card">
        <Status loading={home.loading && !h} error={home.error} loadingText="Reading your sensor and running the forecast…">
          {h ? <>
            <div className="hero">
              <div>
                <div className={`num tone-${g.tone}`}>{g.value}<span className="unit">mg/dL</span></div>
                <div className={`trend tone-${g.tone}`}><span className="arrow">{g.arrow}</span>{g.word}</div>
                <div className="sub">{g.tone === 'good' ? 'in your target range' : g.tone === 'bad' ? 'below your target range' : 'above your target range'} ({Math.round(g.target_low)}–{Math.round(g.target_high)} mg/dL) · as of {nowLabel}</div>
              </div>
              <ChartBox height={220}>
                <ResponsiveContainer width="100%" height={220}>
                  <ComposedChart data={data} margin={{ left: 0, right: 34, top: 18, bottom: 4 }}>
                    <CartesianGrid {...GRID} vertical={false} />
                    <XAxis dataKey="t" tick={TICK} ticks={hourTicks} interval={0} />
                    <YAxis domain={[40, 300]} tick={TICK} width={40} ticks={[70, 180, 250]} />
                    <Tooltip contentStyle={TIP} formatter={(v, n) => (n === 'likely range' ? [null, null] : [`${Math.round(v)} mg/dL`, n])} labelFormatter={(l) => `at ${l}`} />
                    <ReferenceArea y1={g.target_low} y2={g.target_high} fill={COLORS.range} fillOpacity={0.08} />
                    <ReferenceLine x={nowLabel} stroke={COLORS.s4} strokeDasharray="3 3" label={{ value: 'now', position: 'top', fontSize: 11, fill: COLORS.s4 }} />
                    <Area type="monotone" dataKey="p10" stackId="b" stroke="none" fill="transparent" isAnimationActive={false} legendType="none" tooltipType="none" />
                    <Area type="monotone" dataKey="band" stackId="b" stroke="none" fill={COLORS.accent} fillOpacity={0.13} isAnimationActive={false} name="likely range" />
                    <Line className="sensor" type="monotone" dataKey="actual" stroke={COLORS.cgm} dot={false} strokeWidth={2.2} isAnimationActive={false} name="sensor" connectNulls={false} />
                    <Line className="forecast" type="monotone" dataKey="median" stroke={COLORS.accent} strokeOpacity={0.65} dot={false} strokeWidth={1.6} strokeDasharray="5 4" isAnimationActive={false} name="forecast" />
                  </ComposedChart>
                </ResponsiveContainer>
              </ChartBox>
            </div>
            <div className="note">Last 3 hours from your sensor (solid), next 3 hours forecast (dashed, shaded where it will most likely be). The green band is your target range.{gaps.length ? gaps.map((gp) => <span key={gp.start}> · sensor gap {fmtTime(gp.start)}–{fmtTime(gp.end)}</span>) : null}</div>
          </> : null}
        </Status>
      </div>

      <div className="section">
        <h3>Right now</h3>
        <Status loading={home.loading && !h} error={home.error} loadingText="Estimating what is in your body right now…">
          {h ? <div className="tiles">{h.tiles.map((t) => <Tile key={t.key} tile={t} open={open === t.key} onClick={() => setOpen(open === t.key ? null : t.key)} />)}</div> : null}
        </Status>
        {tile ? (
          <div className="card tile-detail">
            <div className="tile-detail-head"><span>{tile.icon} <b>{tile.label}</b> · next 3 hours{tile.unit ? ` (${tile.unit.replace('/ ', 'out of ')})` : ''}</span><button className="small ghost" onClick={() => setOpen(null)}>close</button></div>
            <div className="muted small">{tile.note}</div>
            <ResponsiveContainer width="100%" height={110}>
              <LineChart data={tile.forecast.times.map((x, i) => ({ t: fmtTime(x), v: tile.forecast.values[i] }))} margin={{ left: 0, right: 16, top: 8, bottom: 0 }}>
                <XAxis dataKey="t" tick={TICK} ticks={tile.forecast.times.map(fmtTime).filter((x) => x.endsWith(':00'))} interval={0} />
                <YAxis tick={TICK} width={44} domain={['auto', 'auto']} />
                <Tooltip contentStyle={TIP} formatter={(v) => [`${v} ${tile.unit || ''}`.trim(), tile.label]} labelFormatter={(l) => `at ${l}`} />
                <Line type="monotone" dataKey="v" stroke={COLORS.accent} dot={false} strokeWidth={2} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : null}
        {h ? <div className="faint xs">Whatever is furthest from normal or changing fastest comes first. Tap a tile for its next 3 hours.</div> : null}
      </div>

      <div className="section">
        <h3>Coming up</h3>
        <Status loading={home.loading && !h} error={home.error} loadingText="Looking at the next 8 hours…">
          {h ? <div className="coming">
            {h.coming_up.map((c) => (
              <div key={c.key} className="card">
                <div className="title"><span>{c.icon}</span>{c.title}</div>
                {c.time ? <div className={`when ${c.tone ? `tone-${c.tone}` : ''}`}>{fmtTime(c.time)}<span className="faint xs"> {fmtRel(c.time, nowIso).split(' at ')[0]}</span></div> : <div className={`when ${c.tone ? `tone-${c.tone}` : ''}`}>—</div>}
                <div className="text">{c.text}</div>
              </div>
            ))}
          </div> : null}
        </Status>
      </div>
    </>
  )
}
