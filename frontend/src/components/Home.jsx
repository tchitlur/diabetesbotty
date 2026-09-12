import React, { useEffect, useState } from 'react'
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ReferenceLine, ReferenceArea, ResponsiveContainer, CartesianGrid } from 'recharts'
import { fmtTime, fmtRel, minutesBetween } from '../api.js'
import Status, { ChartBox } from './Status.jsx'
import Tile from './Tile.jsx'
import TileDetail from './TileDetail.jsx'
import Sheet from './Sheet.jsx'
import { useMobile } from '../hooks.js'
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

// One display series on a numeric time axis (minutes since the window start): sensor
// (now-3 h .. now, short gaps interpolated by the backend, long gaps kept as breaks) then the
// forecast anchored on the last sensor point.
function buildSeries(h) {
  const t0 = h.history.times[0]
  const actual = smooth3(h.history.display)
  const rows = h.history.times.map((t, i) => ({ m: minutesBetween(t0, t), iso: t, actual: actual[i] == null ? null : Math.round(actual[i] * 10) / 10 }))
  const last = rows.length && rows[rows.length - 1].actual != null ? rows[rows.length - 1].actual : null
  const f = h.forecast
  const offset = last != null ? last - f.median[0] : 0   // the model's estimate vs the sensor: blend the difference away over the first hour
  f.times.forEach((t, i) => {
    const w = Math.max(0, 1 - i / 12)
    const m = minutesBetween(t0, t)
    const row = { m, iso: t, median: f.median[i] + offset * w, p10: f.p10[i] + offset * w, band: f.p90[i] - f.p10[i] }
    if (i === 0 && rows.length && Math.abs(rows[rows.length - 1].m - m) < 1) Object.assign(rows[rows.length - 1], row)
    else rows.push(row)
  })
  return { rows, t0 }
}

// One line about the twin, rotating through the top personalisation facts.
function TwinLine({ twin }) {
  const lines = twin?.lines || []
  const [i, setI] = useState(0)
  useEffect(() => {
    if (lines.length < 2) return undefined
    const id = setInterval(() => setI((k) => (k + 1) % lines.length), 9000)
    return () => clearInterval(id)
  }, [lines.length])
  if (!twin) return null
  const text = lines.length ? lines[i % lines.length].text : twin.summary
  return <div className="twin-line" data-testid="twin-line"><span className="dna" aria-hidden="true">🧬</span>{text}. {twin.learned}.</div>
}

// Home: the hero card (number + chart + caption + twin line), COMING UP, RIGHT NOW.
export default function Home({ home, nowIso }) {
  const [open, setOpen] = useState(null)
  const mobile = useMobile()
  const h = home.data
  const g = h?.glucose
  const { rows: data, t0 } = h ? buildSeries(h) : { rows: [], t0: null }
  const hourTicksAll = data.filter((d) => d.iso.slice(14, 16) === '00').map((d) => d.m)
  const hourTicks = mobile && hourTicksAll.length > 4 ? hourTicksAll.filter((_, i) => i % 2 === 0).slice(0, 4) : hourTicksAll
  const nowM = h ? minutesBetween(t0, h.wall_now) : 0
  const gaps = h?.history?.gaps || []
  const tile = h && open ? h.tiles.find((t) => t.key === open) : null
  const isoAt = (m) => data.find((r) => Math.abs(r.m - m) < 0.5)?.iso || ''
  const chartH = mobile ? 180 : 220
  const detail = tile ? <TileDetail tile={tile} nowIso={h.wall_now} onClose={() => setOpen(null)} bare={mobile} /> : null
  return (
    <>
      <div className="card hero-card" data-wall-now={h?.wall_now || ''}>
        <Status loading={home.loading && !h} error={home.error} loadingText="Reading your sensor and running the forecast…">
          {h ? <>
            <div className="hero">
              <div className="hero-num">
                <div className={`num tone-${g.tone}`}>{g.value}<span className="unit">mg/dL</span></div>
                <div className={`trend tone-${g.tone}`}><span className="arrow">{g.arrow}</span>{g.word}</div>
                <div className="sub">{g.tone === 'good' ? 'in your target range' : g.tone === 'bad' ? 'below your target range' : 'above your target range'} ({Math.round(g.target_low)}–{Math.round(g.target_high)} mg/dL) · reading from {fmtTime(h.as_of)}</div>
              </div>
              <ChartBox height={chartH}>
                <ResponsiveContainer width="100%" height={chartH}>
                  <ComposedChart data={data} margin={{ left: 0, right: mobile ? 12 : 34, top: 18, bottom: 4 }}>
                    <CartesianGrid {...GRID} vertical={false} />
                    <XAxis dataKey="m" type="number" domain={['dataMin', 'dataMax']} ticks={hourTicks} tick={TICK} tickFormatter={(m) => fmtTime(isoAt(m))} />
                    <YAxis domain={[40, 300]} tick={TICK} width={40} ticks={[70, 180, 250]} />
                    <Tooltip contentStyle={TIP} formatter={(v, n) => (n === 'likely range' ? [null, null] : [`${Math.round(v)} mg/dL`, n])} labelFormatter={(m) => `at ${fmtTime(isoAt(m))}`} />
                    <ReferenceArea y1={g.target_low} y2={g.target_high} fill={COLORS.range} fillOpacity={0.08} />
                    <ReferenceLine x={nowM} stroke={COLORS.s4} strokeDasharray="3 3" label={{ value: 'now', position: 'top', fontSize: 13, fill: COLORS.s4 }} />
                    <Area type="monotone" dataKey="p10" stackId="b" stroke="none" fill="transparent" isAnimationActive={false} legendType="none" tooltipType="none" />
                    <Area type="monotone" dataKey="band" stackId="b" stroke="none" fill={COLORS.accent} fillOpacity={0.13} isAnimationActive={false} name="likely range" />
                    <Line className="sensor" type="monotone" dataKey="actual" stroke={COLORS.cgm} dot={false} strokeWidth={2.2} isAnimationActive={false} name="sensor" connectNulls={false} />
                    <Line className="forecast" type="monotone" dataKey="median" stroke={COLORS.accent} strokeOpacity={0.65} dot={false} strokeWidth={1.6} strokeDasharray="5 4" isAnimationActive={false} name="forecast" />
                  </ComposedChart>
                </ResponsiveContainer>
              </ChartBox>
            </div>
            <div className="note">Last 3 hours from your sensor (solid), next 3 hours forecast (dashed, shaded where it will most likely be). The green band is your target range.{gaps.length ? gaps.map((gp) => <span key={gp.start}> · sensor gap {fmtTime(gp.start)}–{fmtTime(gp.end)}</span>) : null}</div>
            <TwinLine twin={h.twin} />
          </> : null}
        </Status>
      </div>

      <div className="section">
        <h3>Coming up</h3>
        <Status loading={home.loading && !h} error={home.error} loadingText="Looking at the next 8 hours…">
          {h ? <div className={`coming ${mobile ? 'snap' : ''}`} data-testid="coming-up">
            {h.coming_up.map((c) => (
              <div key={c.key} className="card">
                <div className="title"><span>{c.icon}</span>{c.title}</div>
                {c.key === 'risk'
                  ? <div className={`when tone-${c.tone || 'good'}`}><span className="risk-icon">{c.tone === 'good' || !c.tone ? '✓' : '!'}</span><i className={`risk-bar ${c.tone || 'good'}`} /></div>
                  : c.time ? <div className={`when ${c.tone ? `tone-${c.tone}` : ''}`}>{fmtTime(c.time)}<span className="faint xs"> {fmtRel(c.time, nowIso).split(' at ')[0]}</span></div> : <div className="when">—</div>}
                <div className="text">{c.text}</div>
              </div>
            ))}
          </div> : null}
        </Status>
      </div>

      <div className="section">
        <h3>Right now</h3>
        <Status loading={home.loading && !h} error={home.error} loadingText="Estimating what is in your body right now…">
          {h ? <div className="tiles">{h.tiles.map((t) => <Tile key={t.key} tile={t} open={open === t.key} onClick={() => setOpen(open === t.key ? null : t.key)} />)}</div> : null}
        </Status>
        {tile && !mobile ? detail : null}
        {tile && mobile ? <Sheet title={`${tile.icon} ${tile.label}`} onClose={() => setOpen(null)} testId="tile-sheet">{detail}</Sheet> : null}
        {h ? <div className="faint xs">Whatever is furthest from normal or changing fastest comes first. Tap a tile for more.</div> : null}
      </div>
    </>
  )
}
