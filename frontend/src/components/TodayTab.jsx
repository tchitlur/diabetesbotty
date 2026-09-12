import React, { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { api, fmtTime, pct } from '../api.js'
import PermissionCard from './PermissionCard.jsx'
import ChangeCard from './ChangeCard.jsx'

export default function TodayTab({ cards, planned, forecastKey, onAccepted }) {
  const [plan, setPlan] = useState(null)
  const [alerts, setAlerts] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const load = async () => {
    setBusy(true)
    try {
      const [p, a] = await Promise.all([api.plan(0), api.alerts()])
      setPlan(p); setAlerts(a); setErr(null)
    } catch (e) { setErr(String(e.message)) } finally { setBusy(false) }
  }
  useEffect(() => { load() }, [forecastKey])
  const energy = plan ? plan.energy_times.map((t, i) => ({ t: fmtTime(t), e: plan.energy_curve[i] })) : []
  return (
    <div className="grid" style={{ gridTemplateColumns: '1fr' }}>
      <div className="card">
        <h3>Tomorrow's plan {plan ? `(${plan.date})` : ''} {busy ? <span className="spinner" /> : null}</h3>
        {err ? <div className="err">{err}</div> : null}
        {plan ? (
          <>
            <div className="timeline">
              {plan.timeline.map((b) => <div key={b.start} className={`tl-block ${b.color}`} title={`${fmtTime(b.start)}–${fmtTime(b.end)}: ${b.label}`}><div className="h">{fmtTime(b.start).slice(0, 2)}</div>{b.label.split(' - ')[0].slice(0, 14)}</div>)}
            </div>
            <div className="tl-legend"><span>■ green: in range</span><span style={{ color: 'var(--amber)' }}>■ amber: near low / above 180</span><span style={{ color: 'var(--red)' }}>■ red: below 70 / above 250</span></div>
            <div style={{ marginTop: 10 }} className="kv">
              <span className="k">Workout</span><b>{plan.workout_start ? plan.workout_start.replace('T', ' ') : '–'}</b><span />
              <span className="k">Snack</span><b>{plan.snack_time ? plan.snack_time.replace('T', ' ') : 'none needed'}</b><span />
              <span className="k">Drink cutoff</span><b>{plan.drink_cutoff ? fmtTime(plan.drink_cutoff) : 'no drinks planned'}</b><span />
              <span className="k">P(hypo) around workout</span><b>{pct(plan.p_hypo)}</b><span />
              <span className="k">Day TIR</span><b>{pct(plan.tir)}</b><span />
            </div>
            <div className="sub" style={{ marginTop: 6 }}>{plan.notes.join(' ')}</div>
            <ResponsiveContainer width="100%" height={120}>
              <LineChart data={energy} margin={{ left: 0, right: 10, top: 8, bottom: 0 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="t" tick={{ fontSize: 10, fill: 'var(--muted)' }} interval={5} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: 'var(--muted)' }} width={30} />
                <Tooltip contentStyle={{ background: '#0b0f14', border: '1px solid var(--border)' }} />
                <Line type="monotone" dataKey="e" stroke="var(--green)" dot={false} name="energy" isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </>
        ) : <div className="muted">planning…</div>}
      </div>

      <div className="grid two">
        <div className="card">
          <h3>Pending alerts (do-nothing forecast)</h3>
          {alerts == null ? <div className="muted">…</div> : alerts.length === 0 ? <div className="muted">No crossing of 70 / 250 with P ≥ 15 % in the next 8 h.</div> : alerts.map((a, i) => (
            <div key={i} className={`alert ${a.kind}`}><b>{a.kind.toUpperCase()}</b> {a.message}</div>
          ))}
        </div>
        <div className="card">
          <h3>Committed to the plan</h3>
          {planned.length === 0 ? <div className="muted">Nothing yet. Approve a card in the chat and tap "Add to plan".</div> : (
            <table><thead><tr><th>when</th><th>event</th><th>amount</th></tr></thead><tbody>
              {planned.map((e, i) => <tr key={i}><td>{e.start_time.replace('T', ' ')}</td><td>{e.label || e.type}</td><td className="num">{e.carbs_g ? `${e.carbs_g.toFixed(0)} g carbs ` : ''}{e.alcohol_g ? `${e.alcohol_g.toFixed(0)} g alc ` : ''}{e.caffeine_mg ? `${e.caffeine_mg.toFixed(0)} mg ` : ''}{e.type === 'exercise' ? `${e.duration_min.toFixed(0)} min` : ''}</td></tr>)}
            </tbody></table>
          )}
        </div>
      </div>

      <div className="card">
        <h3>Cards from this session</h3>
        {cards.length === 0 ? <div className="muted">Ask the chat something ("can I have two more beers tonight?") and the card lands here too.</div> : (
          <div className="grid" style={{ gridTemplateColumns: '1fr' }}>
            {cards.map((c) => c.kind === 'change' ? <ChangeCard key={c.at} resp={c.payload} compact /> : <PermissionCard key={c.at} card={c.payload} compact onAccepted={onAccepted} />)}
          </div>
        )}
      </div>
    </div>
  )
}
