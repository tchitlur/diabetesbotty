import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, ReferenceLine } from 'recharts'
import { api } from '../api.js'
import Header from './Header.jsx'
import Status from './Status.jsx'
import { TICK, TIP, GRID, xLabel, yLabel, MARGIN, COLORS } from './chart.js'

const SENS = [['si_tod0', 'night sensitivity (×)', COLORS.accent], ['si_tod1', 'day sensitivity (×)', COLORS.good], ['si_tod2', 'evening sensitivity (×)', COLORS.warn], ['carb_ratio', 'carb bioavailability', COLORS.s2]]
const GAINS = [['exercise_mult', 'exercise gain', COLORS.accent], ['alcohol_gain', 'alcohol gain', COLORS.bad], ['basal_drift', 'basal drift', COLORS.good], ['sleep_debt_coef', 'sleep-debt coefficient', COLORS.s3]]
const M = { ...MARGIN, bottom: 22 }

export default function Clinician() {
  const [c, setC] = useState(null)
  const [hdr, setHdr] = useState({})
  const [err, setErr] = useState(null)
  useEffect(() => {
    api.clinician().then(setC).catch((e) => setErr(String(e.message)))
    Promise.all([api.health(), api.state(), api.drift(), api.parserStatus()]).then(([health, state, drift, parser]) => setHdr({ health, state, drift, parser })).catch(() => {})
  }, [])
  const pd = c ? c.parameter_drift.map((r) => ({ ...r, d: r.date.slice(5) })) : []
  const rl = c ? c.residual_log.map((r) => ({ ...r, d: r.date.slice(5) })) : []
  const drift = (title, series, note) => (
    <div className="card">
      <h3>{title}</h3>
      <Status loading={!c && !err} error={err} loadingText="Loading refit history…">
        {c ? <ResponsiveContainer width="100%" height={240}>
          <LineChart data={pd} margin={M}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="d" tick={TICK} label={xLabel('end of 14-day refit window (MM-DD)')} />
            <YAxis tick={TICK} width={40} domain={[0, 'auto']} tickFormatter={(v) => Number(v).toFixed(1)} label={yLabel('fitted value')} />
            <Tooltip contentStyle={TIP} formatter={(v, n) => [Number(v).toFixed(3), n]} />
            {series.map(([k, name, color]) => <Line key={k} type="monotone" dataKey={k} stroke={color} dot={{ r: 2 }} name={name} isAnimationActive={false} />)}
            <Legend wrapperStyle={{ fontSize: 11, paddingTop: 12 }} />
          </LineChart>
        </ResponsiveContainer> : null}
      </Status>
      <div className="note">{note}</div>
    </div>
  )
  return (
    <div className="app">
      <Header health={hdr.health} state={hdr.state} drift={hdr.drift} parser={hdr.parser} right={<Link to="/" className="pill">← Patient dashboard</Link>} />
      <div className="content">
        <div className="clin">
          <h2 style={{ marginBottom: 'var(--s2)' }}>Clinician view</h2>
          <p className="muted small" style={{ marginBottom: 'var(--s4)' }}>Everything here is backend output for the synthetic demo patient: how the twin's parameters moved over 12 weeks, how well its 60-minute forecast tracked the sensor, and what the safety gate escalated. Decision support only; nothing doses insulin.</p>
          <div className="grid two">
            {drift('Parameter drift: insulin sensitivities and carb bioavailability', SENS, 'Sliding 14-day refits every 7 days (8 Gauss-Newton iterations each). Night/day/evening are the three time-of-day bins.')}
            {drift('Parameter drift: exercise, alcohol, basal, sleep', GAINS, 'Alcohol gain has the widest posterior (few drinking nights per window); its swings are expected.')}
            <div className="card">
              <h3>Residual log: daily RMSE of the 60-minute forecast (live period)</h3>
              <Status loading={!c && !err} error={err}>
                {c ? <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={rl} margin={M}>
                    <CartesianGrid {...GRID} />
                    <XAxis dataKey="d" tick={TICK} interval={4} label={xLabel('date (MM-DD)')} />
                    <YAxis tick={TICK} width={40} label={yLabel('RMSE (mg/dL)')} />
                    <Tooltip contentStyle={TIP} formatter={(v, n) => [`${Number(v).toFixed(1)} mg/dL`, n]} />
                    <ReferenceLine y={20} stroke={COLORS.warn} strokeDasharray="4 4" />
                    <Line type="monotone" dataKey="rmse_ode_60" stroke={COLORS.s4} dot={false} name="ODE only" isAnimationActive={false} />
                    <Line type="monotone" dataKey="rmse_combined_60" stroke={COLORS.accent} dot={false} strokeWidth={2} name="ODE + residual model" isAnimationActive={false} />
                    <Legend wrapperStyle={{ fontSize: 11, paddingTop: 12 }} />
                  </LineChart>
                </ResponsiveContainer> : null}
              </Status>
              <div className="note">Dashed amber line: the 20 mg/dL target. Drift is flagged after 3 consecutive rising days; the gate escalates at 5.</div>
            </div>
            <div className="card">
              <h3>Fitted parameters: posterior mean ± std (30 bootstrap resamples)</h3>
              <Status loading={!c && !err} error={err}>
                {c ? <table><thead><tr><th>parameter</th><th className="num">mean</th><th className="num">std</th><th className="num">population prior</th></tr></thead>
                  <tbody>{Object.entries(c.fitted_params).map(([k, v]) => <tr key={k}><td>{k}</td><td className="num">{v.mean.toFixed(3)}</td><td className="num">{v.std.toFixed(3)}</td><td className="num">{v.prior.toFixed(3)}</td></tr>)}</tbody></table> : null}
              </Status>
            </div>
            <div className="card">
              <h3>Escalation history (this session)</h3>
              <Status loading={!c && !err} error={err} empty={c && c.escalation_history.length === 0} emptyText="No escalations. The gate escalates on a DKA pattern, 3+ severe-hypo episodes in 24 h, or 5+ days of flagged drift.">
                {c ? <table><thead><tr><th>at</th><th>reason</th><th>instruction</th></tr></thead><tbody>{c.escalation_history.map((e, i) => <tr key={i}><td>{e.at.replace('T', ' ')}</td><td>{e.reason}</td><td>{e.instruction}</td></tr>)}</tbody></table> : null}
              </Status>
            </div>
            <div className="card">
              <h3>Drift history (daily)</h3>
              <Status loading={!c && !err} error={err} empty={c && c.drift.history.length === 0} emptyText="No drift history yet.">
                {c ? <div className="tablewrap" style={{ maxHeight: 220, overflowY: 'auto' }}><table><thead><tr><th>date</th><th className="num">ODE + residual RMSE</th><th className="num">ODE-only RMSE</th></tr></thead><tbody>{c.drift.history.map((h) => <tr key={h.date}><td>{h.date}</td><td className="num">{Number(h.rmse).toFixed(1)}</td><td className="num">{Number(h.rmse_ode).toFixed(1)}</td></tr>)}</tbody></table></div> : null}
              </Status>
            </div>
          </div>
          <div className="card" style={{ marginTop: 'var(--s4)' }}>
            <h3>Refit table</h3>
            <Status loading={!c && !err} error={err}>
              {c ? <div className="tablewrap"><table><thead><tr><th>window end</th><th className="num">RMSE (mg/dL)</th>{[...SENS, ...GAINS].map(([k]) => <th key={k} className="num">{k}</th>)}<th className="num">tau_carb (min)</th></tr></thead>
                <tbody>{pd.map((r) => <tr key={r.date}><td>{r.date}</td><td className="num">{r.rmse.toFixed(1)}</td>{[...SENS, ...GAINS].map(([k]) => <td key={k} className="num">{r[k].toFixed(3)}</td>)}<td className="num">{r.tau_carb.toFixed(1)}</td></tr>)}</tbody></table></div> : null}
            </Status>
          </div>
        </div>
      </div>
    </div>
  )
}
