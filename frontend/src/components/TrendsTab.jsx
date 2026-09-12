import React, { useEffect, useState } from 'react'
import { LineChart, Line, ScatterChart, Scatter, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Legend } from 'recharts'
import { api } from '../api.js'

const tick = { fontSize: 10, fill: 'var(--muted)' }
const tip = { background: '#0b0f14', border: '1px solid var(--border)', fontSize: 11 }

export default function TrendsTab() {
  const [t, setT] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { api.trends().then(setT).catch((e) => setErr(String(e.message))) }, [])
  if (err) return <div className="err">{err}</div>
  if (!t) return <div className="muted">loading trends…</div>
  const daily = t.daily.map((r) => ({ ...r, d: r.date.slice(5) }))
  const last = daily[daily.length - 1]
  const proj = [{ d: 'now', hba1c: last?.hba1c }, ...t.a1c_projection.map((p) => ({ d: `+${p.day}d`, hba1c: p.hba1c }))]
  const scatter = daily.filter((r) => r.sleep_hours != null).map((r) => ({ x: r.sleep_hours, y: r.insulin_sensitivity }))
  return (
    <div className="grid two">
      <div className="card">
        <h3>HbA1c: observed twin estimate and 90-day projection under the current week</h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={[...daily.map((r) => ({ d: r.d, hba1c: r.hba1c })), ...proj.slice(1).map((p) => ({ d: p.d, proj: p.hba1c }))]} margin={{ left: 0, right: 10, top: 8, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="d" tick={tick} interval={13} />
            <YAxis domain={[5, 9]} tick={tick} width={30} />
            <Tooltip contentStyle={tip} />
            <ReferenceLine y={7} stroke="var(--amber)" strokeDasharray="4 4" />
            <Line type="monotone" dataKey="hba1c" stroke="var(--accent)" dot={false} name="A1c (%)" isAnimationActive={false} />
            <Line type="monotone" dataKey="proj" stroke="var(--purple)" dot={false} strokeDasharray="5 3" name="projection" isAnimationActive={false} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
          </LineChart>
        </ResponsiveContainer>
        <div className="sub">Steady-state A1c for the current mean glucose: {t.a1c_steady} %.</div>
      </div>
      <div className="card">
        <h3>Insulin-sensitivity drift (effective multiplier, sleep debt applied)</h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={daily} margin={{ left: 0, right: 10, top: 8, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="d" tick={tick} interval={13} />
            <YAxis yAxisId="l" domain={[0.6, 1.3]} tick={tick} width={34} />
            <YAxis yAxisId="r" orientation="right" domain={[0, 6]} tick={tick} width={30} />
            <Tooltip contentStyle={tip} />
            <ReferenceLine yAxisId="l" y={1} stroke="var(--muted)" strokeDasharray="4 4" />
            <Line yAxisId="l" type="monotone" dataKey="insulin_sensitivity" stroke="var(--green)" dot={false} name="sensitivity ×" isAnimationActive={false} />
            <Line yAxisId="r" type="monotone" dataKey="sleep_debt" stroke="var(--amber)" dot={false} name="sleep debt (h, right)" isAnimationActive={false} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="card">
        <h3>Hypo frequency (hours per day below 70 mg/dL)</h3>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={daily} margin={{ left: 0, right: 10, top: 8, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="d" tick={tick} interval={13} />
            <YAxis tick={tick} width={30} />
            <Tooltip contentStyle={tip} />
            <Bar dataKey="hypo_hours" fill="var(--red)" isAnimationActive={false} name="h/day < 70" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="card">
        <h3>Sleep vs insulin sensitivity (one point per day)</h3>
        <ResponsiveContainer width="100%" height={200}>
          <ScatterChart margin={{ left: 0, right: 10, top: 8, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="x" type="number" domain={[4.5, 9.5]} tick={tick} name="sleep (h)" label={{ value: 'sleep last night (h)', position: 'insideBottom', fill: 'var(--muted)', fontSize: 10, offset: -2 }} />
            <YAxis dataKey="y" type="number" domain={[0.6, 1.3]} tick={tick} width={34} name="sensitivity" />
            <Tooltip contentStyle={tip} cursor={{ strokeDasharray: '3 3' }} />
            <Scatter data={scatter} fill="var(--accent)" isAnimationActive={false} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
