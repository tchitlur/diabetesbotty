import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, ReferenceLine } from 'recharts'
import { api } from '../api.js'

const tick = { fontSize: 10, fill: 'var(--muted)' }
const tip = { background: '#0b0f14', border: '1px solid var(--border)', fontSize: 11 }
const PARAMS = ['si_tod0', 'si_tod1', 'si_tod2', 'carb_ratio', 'exercise_mult', 'alcohol_gain', 'basal_drift', 'sleep_debt_coef']
const COLORS = ['#4cc9f0', '#3fb950', '#d29922', '#f85149', '#a371f7', '#ff7eb6', '#8b98a8', '#e6edf3']

export default function Clinician() {
  const [c, setC] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { api.clinician().then(setC).catch((e) => setErr(String(e.message))) }, [])
  if (err) return <div className="clin"><div className="err">{err}</div></div>
  if (!c) return <div className="clin muted">loading…</div>
  const pd = c.parameter_drift.map((r) => ({ ...r, d: r.date.slice(5) }))
  const rl = c.residual_log.map((r) => ({ ...r, d: r.date.slice(5) }))
  return (
    <div className="clin">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h1 style={{ margin: 0 }}>GlucoPilot — clinician view</h1>
        <Link to="/" className="pill">← patient dashboard</Link>
        <span className="pill"><span className={`dot ${c.drift.flagged ? 'amber' : 'green'}`} /> drift score {c.drift.score}{c.drift.flagged ? ` (flagged since ${c.drift.since})` : ''}</span>
      </div>
      <p className="muted">All values are real backend output for the synthetic demo patient. Decision support only; no dosing is automated.</p>
      <div className="grid two">
        <div className="card">
          <h3>Parameter drift (sliding 14-day refits every 7 days)</h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={pd} margin={{ left: 0, right: 10, top: 8, bottom: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis dataKey="d" tick={tick} />
              <YAxis tick={tick} width={34} domain={[0, 'auto']} tickFormatter={(v) => Number(v).toFixed(2)} />
              <Tooltip contentStyle={tip} />
              {PARAMS.map((p, i) => <Line key={p} type="monotone" dataKey={p} stroke={COLORS[i]} dot={{ r: 2 }} isAnimationActive={false} />)}
              <Legend wrapperStyle={{ fontSize: 10 }} />
            </LineChart>
          </ResponsiveContainer>
          <div className="sub">tau_carb (minutes) omitted from the axis; see the table.</div>
        </div>
        <div className="card">
          <h3>Residual log (daily RMSE of the 60-min forecast, live period)</h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={rl} margin={{ left: 0, right: 10, top: 8, bottom: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis dataKey="d" tick={tick} interval={4} />
              <YAxis tick={tick} width={34} />
              <Tooltip contentStyle={tip} />
              <ReferenceLine y={20} stroke="var(--amber)" strokeDasharray="4 4" label={{ value: 'target 20', fill: 'var(--muted)', fontSize: 10 }} />
              <Line type="monotone" dataKey="rmse_ode_60" stroke="#8b98a8" dot={false} name="ODE only" isAnimationActive={false} />
              <Line type="monotone" dataKey="rmse_combined_60" stroke="var(--accent)" dot={false} strokeWidth={2} name="ODE + residual" isAnimationActive={false} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <h3>Fitted parameters (posterior mean ± std, 30 bootstrap resamples)</h3>
          <table><thead><tr><th>parameter</th><th className="num">mean</th><th className="num">std</th><th className="num">prior</th></tr></thead>
            <tbody>{Object.entries(c.fitted_params).map(([k, v]) => <tr key={k}><td>{k}</td><td className="num">{v.mean.toFixed(4)}</td><td className="num">{v.std.toFixed(4)}</td><td className="num">{v.prior.toFixed(4)}</td></tr>)}</tbody></table>
        </div>
        <div className="card">
          <h3>Escalation history (this session)</h3>
          {c.escalation_history.length === 0 ? <div className="muted">No escalations. The gate escalates on DKA pattern, 3+ severe-hypo episodes in 24 h, or 5+ days of flagged drift.</div> : (
            <table><thead><tr><th>at</th><th>reason</th><th>instruction</th></tr></thead><tbody>{c.escalation_history.map((e, i) => <tr key={i}><td>{e.at}</td><td>{e.reason}</td><td>{e.instruction}</td></tr>)}</tbody></table>
          )}
          <h3 style={{ marginTop: 14 }}>Drift history</h3>
          <div className="mono" style={{ maxHeight: 160, overflow: 'auto' }}>
            {c.drift.history.map((h) => <div key={h.date}>{h.date}: combined {h.rmse} · ODE {h.rmse_ode}</div>)}
          </div>
        </div>
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <h3>Refit table</h3>
        <div style={{ overflowX: 'auto' }}>
          <table><thead><tr><th>window end</th><th className="num">rmse</th>{PARAMS.map((p) => <th key={p} className="num">{p}</th>)}<th className="num">tau_carb</th></tr></thead>
            <tbody>{pd.map((r) => <tr key={r.date}><td>{r.date}</td><td className="num">{r.rmse.toFixed(1)}</td>{PARAMS.map((p) => <td key={p} className="num">{r[p].toFixed(3)}</td>)}<td className="num">{r.tau_carb.toFixed(1)}</td></tr>)}</tbody></table>
        </div>
      </div>
    </div>
  )
}
