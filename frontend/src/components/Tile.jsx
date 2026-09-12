import React, { useState } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { fmtTime } from '../api.js'
import { TICK, TIP, COLORS } from './chart.js'

function Gauge({ level, tone }) {
  const v = Math.max(0, Math.min(1, level))
  const ang = Math.PI * (1 - v)
  const r = 32, cx = 42, cy = 40
  const x = cx + r * Math.cos(ang), y = cy - r * Math.sin(ang)
  return (
    <svg className="gauge" viewBox="0 0 84 46">
      <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} stroke="#f1f2ef" strokeWidth="9" fill="none" />
      {v > 0.005 ? <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${x} ${y}`} stroke={COLORS[tone] || COLORS.good} strokeWidth="9" fill="none" strokeLinecap="round" /> : null}
    </svg>
  )
}

// One pictographic tile: icon, plain label, a simple visual, one status word. Tap for its 3-hour forecast.
export default function Tile({ tile }) {
  const [open, setOpen] = useState(false)
  const t = tile
  const fill = `fill-${t.tone}`
  const data = t.forecast.times.map((x, i) => ({ t: fmtTime(x), v: t.forecast.values[i] }))
  return (
    <button type="button" className={`tile ${open ? 'open' : ''}`} onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={`${t.label}: ${t.status}`}>
      <div className="top"><span className="icon">{t.icon}</span><span className="label">{t.label}</span></div>
      <div className="visual">
        {t.visual === 'gauge' ? <Gauge level={t.level} tone={t.tone} /> : null}
        {t.visual === 'level' ? <span className="level"><i className={fill} style={{ height: `${Math.round(100 * t.level)}%` }} /></span> : null}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="val">{t.value_text}{t.sub ? <span className="sub"> {t.sub}</span> : null}</div>
          {t.visual === 'bar' ? <div className="bar"><i className={fill} style={{ width: `${Math.round(100 * t.level)}%` }} /></div> : null}
          <div className={`word tone-${t.tone}`}>{t.status}</div>
        </div>
      </div>
      {open ? (
        <div className="more">
          <div>{t.note}</div>
          <div className="xs faint" style={{ marginTop: 6 }}>Next 3 hours{t.unit ? ` (${t.unit.trim()})` : ''}</div>
          <ResponsiveContainer width="100%" height={90}>
            <LineChart data={data} margin={{ left: 0, right: 8, top: 6, bottom: 0 }}>
              <XAxis dataKey="t" tick={TICK} interval={11} />
              <YAxis tick={TICK} width={44} domain={['auto', 'auto']} />
              <Tooltip contentStyle={TIP} formatter={(v) => [`${v} ${t.unit || ''}`.trim(), t.label]} labelFormatter={(l) => `at ${l}`} />
              <Line type="monotone" dataKey="v" stroke={COLORS.accent} dot={false} strokeWidth={2} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : <div className="tapnote">tap for the next 3 hours</div>}
    </button>
  )
}
