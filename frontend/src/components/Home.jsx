import React from 'react'
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ReferenceLine, ReferenceArea, ResponsiveContainer, CartesianGrid } from 'recharts'
import { fmtTime, fmtRel } from '../api.js'
import Status, { ChartBox } from './Status.jsx'
import Tile from './Tile.jsx'
import { TICK, TIP, GRID, COLORS } from './chart.js'

// Home: one big glucose number, one chart, the "right now" tiles, the "coming up" cards.
export default function Home({ home, nowIso }) {
  const h = home.data
  const g = h?.glucose
  const data = []
  if (h) {
    h.history.times.forEach((t, i) => data.push({ t: fmtTime(t), iso: t, actual: h.history.glucose[i] }))
    h.forecast.times.forEach((t, i) => { if (i === 0 && data.length) { data[data.length - 1].median = h.forecast.median[0]; data[data.length - 1].p10 = h.forecast.p10[0]; data[data.length - 1].band = h.forecast.p90[0] - h.forecast.p10[0]; return } data.push({ t: fmtTime(t), iso: t, median: h.forecast.median[i], p10: h.forecast.p10[i], band: h.forecast.p90[i] - h.forecast.p10[i] }) })
  }
  const nowLabel = h ? fmtTime(h.as_of) : ''
  const hourTicks = data.filter((d) => d.t.endsWith(':00')).map((d) => d.t)
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
                  <ComposedChart data={data} margin={{ left: 0, right: 12, top: 18, bottom: 4 }}>
                    <CartesianGrid {...GRID} vertical={false} />
                    <XAxis dataKey="t" tick={TICK} ticks={hourTicks} interval={0} />
                    <YAxis domain={[40, 300]} tick={TICK} width={40} ticks={[70, 180, 250]} />
                    <Tooltip contentStyle={TIP} formatter={(v, n) => (n === 'likely range' ? [null, null] : [`${Math.round(v)} mg/dL`, n])} labelFormatter={(l) => `at ${l}`} />
                    <ReferenceArea y1={g.target_low} y2={g.target_high} fill={COLORS.range} fillOpacity={0.08} />
                    <ReferenceLine x={nowLabel} stroke={COLORS.s4} strokeDasharray="3 3" label={{ value: 'now', position: 'top', fontSize: 11, fill: COLORS.s4 }} />
                    <Area type="monotone" dataKey="p10" stackId="b" stroke="none" fill="transparent" isAnimationActive={false} legendType="none" tooltipType="none" />
                    <Area type="monotone" dataKey="band" stackId="b" stroke="none" fill={COLORS.accent} fillOpacity={0.15} isAnimationActive={false} name="likely range" />
                    <Line type="monotone" dataKey="actual" stroke={COLORS.cgm} dot={false} strokeWidth={2} isAnimationActive={false} name="sensor" connectNulls={false} />
                    <Line type="monotone" dataKey="median" stroke={COLORS.accent} dot={false} strokeWidth={2} strokeDasharray="5 3" isAnimationActive={false} name="forecast" />
                  </ComposedChart>
                </ResponsiveContainer>
              </ChartBox>
            </div>
            <div className="note">Last 3 hours from your sensor (solid), next 3 hours forecast (dashed, shaded where it will most likely be). The green band is your target range.</div>
          </> : null}
        </Status>
      </div>

      <div className="section">
        <h3>Right now</h3>
        <Status loading={home.loading && !h} error={home.error} loadingText="Estimating what is in your body right now…">
          {h ? <div className="tiles">{h.tiles.map((t) => <Tile key={t.key} tile={t} />)}</div> : null}
        </Status>
        {h ? <div className="faint xs">Tiles that are furthest from normal or changing fastest come first. Tap a tile for its next 3 hours.</div> : null}
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
