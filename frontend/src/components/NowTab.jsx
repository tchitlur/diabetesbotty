import React, { useEffect, useState } from 'react'
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'
import { api, fmtTime, pct } from '../api.js'

const FAST = [
  ['glucose', 'Glucose'], ['plasma_insulin', 'Plasma insulin'], ['gut_carbs_1', 'Gut carbs (1)'], ['gut_carbs_2', 'Gut carbs (2)'],
  ['liver_glycogen', 'Liver glycogen'], ['muscle_glycogen', 'Muscle glycogen'], ['blood_alcohol', 'Blood alcohol'], ['caffeine', 'Caffeine'],
  ['ketones', 'Ketones'], ['hydration', 'Hydration'],
]
const MEDIUM = [['sleep_debt', 'Sleep debt'], ['insulin_sensitivity', 'Insulin sensitivity'], ['training_load', 'Training load'], ['fat_mass', 'Fat mass'], ['lean_mass', 'Lean mass'], ['hba1c', 'HbA1c']]

function fmt(v, k) {
  if (v == null) return '–'
  if (k === 'blood_alcohol') return v.toFixed(3)
  if (k === 'hydration' || k === 'ketones' || k === 'insulin_sensitivity') return v.toFixed(2)
  if (k === 'hba1c') return v.toFixed(2)
  return v.toFixed(v >= 100 ? 0 : 1)
}

function Gauge({ value }) {
  const v = Math.max(0, Math.min(100, value || 0))
  const ang = Math.PI * (1 - v / 100)
  const r = 70, cx = 80, cy = 82
  const x = cx + r * Math.cos(ang), y = cy - r * Math.sin(ang)
  const color = v >= 70 ? 'var(--green)' : v >= 45 ? 'var(--amber)' : 'var(--red)'
  return (
    <div className="gauge">
      <svg width="160" height="90" viewBox="0 0 160 90">
        <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} stroke="var(--panel-2)" strokeWidth="14" fill="none" />
        <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${x} ${y}`} stroke={color} strokeWidth="14" fill="none" strokeLinecap="round" />
      </svg>
      <div className="val">{v.toFixed(0)}</div>
    </div>
  )
}

export default function NowTab({ state, forecastKey }) {
  const [fc, setFc] = useState(null)
  const [hist, setHist] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    let alive = true
    Promise.all([api.forecast(480), api.history(6)]).then(([f, h]) => { if (alive) { setFc(f); setHist(h) } }).catch((e) => setErr(String(e.message)))
    return () => { alive = false }
  }, [forecastKey])

  const data = []
  if (hist) hist.times.forEach((t, i) => data.push({ t: fmtTime(t), actual: hist.glucose[i] }))
  if (fc) fc.times.forEach((t, i) => data.push({ t: fmtTime(t), median: fc.median[i], p10: fc.p10[i], band: fc.p90[i] - fc.p10[i], ins: fc.substances.insulin?.[i], alc: fc.substances.alcohol?.[i], caf: fc.substances.caffeine?.[i] }))
  const sub = fc ? fc.times.map((t, i) => ({ t: fmtTime(t), insulin: fc.substances.insulin?.[i], alcohol: fc.substances.alcohol?.[i], caffeine: fc.substances.caffeine?.[i] })) : []

  return (
    <div className="grid" style={{ gridTemplateColumns: '1fr' }}>
      {err ? <div className="err">{err}</div> : null}
      <div className="grid three">
        <div className="card">
          <h3>Glucose now (estimated)</h3>
          <div className="big">{state ? `${state.values.glucose.toFixed(0)} ± ${state.std.glucose.toFixed(0)}` : '…'} <span className="sub">mg/dL</span></div>
          <div className="sub">UKF estimate as of {state ? state.as_of.replace('T', ' ') : ''}</div>
        </div>
        <div className="card">
          <h3>8 h forecast</h3>
          <div className="kv">
            <span className="k">P(hypo &lt; 70)</span><b>{fc ? pct(fc.p_hypo_8h) : '…'}</b><span />
            <span className="k">P(hyper &gt; 250)</span><b>{fc ? pct(fc.p_hyper_8h) : '…'}</b><span />
            <span className="k">Time in range</span><b>{fc ? pct(fc.tir) : '…'}</b><span />
          </div>
          <div className="sub">200 Monte Carlo trajectories over the fitted posterior + residual model</div>
        </div>
        <div className="card">
          <h3>Energy score</h3>
          <Gauge value={state?.values.energy_score} />
          <div className="sub" style={{ textAlign: 'center' }}>from |glucose − 100|, sleep debt, caffeine, hydration</div>
        </div>
      </div>

      <div className="card">
        <h3>Last 6 h (CGM) and next 8 h (median with p10–p90 band)</h3>
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={data} margin={{ left: 0, right: 10, top: 5, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="t" tick={{ fontSize: 11, fill: 'var(--muted)' }} interval={11} />
            <YAxis domain={[40, 300]} tick={{ fontSize: 11, fill: 'var(--muted)' }} width={36} />
            <Tooltip contentStyle={{ background: '#0b0f14', border: '1px solid var(--border)' }} />
            <ReferenceLine y={70} stroke="var(--red)" strokeDasharray="4 4" />
            <ReferenceLine y={180} stroke="var(--amber)" strokeDasharray="4 4" />
            <ReferenceLine y={250} stroke="var(--red)" strokeDasharray="2 6" />
            <Area type="monotone" dataKey="p10" stackId="b" stroke="none" fill="transparent" isAnimationActive={false} />
            <Area type="monotone" dataKey="band" stackId="b" stroke="none" fill="var(--accent)" fillOpacity={0.18} isAnimationActive={false} name="p10–p90" />
            <Line type="monotone" dataKey="actual" stroke="#e6edf3" dot={false} strokeWidth={1.5} isAnimationActive={false} name="CGM" connectNulls={false} />
            <Line type="monotone" dataKey="median" stroke="var(--accent)" dot={false} strokeWidth={2} isAnimationActive={false} name="forecast median" />
            <Legend wrapperStyle={{ fontSize: 11 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="grid two">
        <div className="card">
          <h3>Active substances (median decay over the forecast)</h3>
          <ResponsiveContainer width="100%" height={180}>
            <ComposedChart data={sub} margin={{ left: 0, right: 10, top: 5, bottom: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis dataKey="t" tick={{ fontSize: 11, fill: 'var(--muted)' }} interval={11} />
              <YAxis yAxisId="l" tick={{ fontSize: 11, fill: 'var(--muted)' }} width={36} />
              <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11, fill: 'var(--muted)' }} width={40} domain={[0, 0.15]} />
              <Tooltip contentStyle={{ background: '#0b0f14', border: '1px solid var(--border)' }} />
              <Line yAxisId="l" type="monotone" dataKey="insulin" stroke="var(--accent)" dot={false} name="plasma insulin (mU/L)" isAnimationActive={false} />
              <Line yAxisId="l" type="monotone" dataKey="caffeine" stroke="var(--amber)" dot={false} name="caffeine (mg)" isAnimationActive={false} />
              <Line yAxisId="r" type="monotone" dataKey="alcohol" stroke="var(--purple)" dot={false} name="BAC (g/dL)" isAnimationActive={false} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <h3>Estimated state (± std for the fast layer)</h3>
          <div className="kv">
            {FAST.map(([k, l]) => (
              <React.Fragment key={k}>
                <span className="k">{l}</span>
                <span className="mono">{state ? `${fmt(state.values[k], k)}${state.std[k] != null ? ` ± ${fmt(state.std[k], k)}` : ''}` : '…'}</span>
                <span className="u">{state?.units[k]}</span>
              </React.Fragment>
            ))}
            {MEDIUM.map(([k, l]) => (
              <React.Fragment key={k}>
                <span className="k">{l}</span>
                <span className="mono">{state ? fmt(state.values[k], k) : '…'}</span>
                <span className="u">{state?.units[k]}</span>
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
