import React, { useState } from 'react'
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'
import { api, fmtTime, pct } from '../api.js'

const VERDICT = {
  approved: 'Approved', approved_with_condition: 'Approved with condition', denied: 'Denied',
  request_data: 'Need data first', escalate: 'Escalate to care team',
}

export default function PermissionCard({ card, compact = false, onAccepted, onWhy }) {
  const [added, setAdded] = useState(false)
  const [busy, setBusy] = useState(false)
  const mc = card.mini_curve
  const data = mc ? mc.times.map((t, i) => ({ t: fmtTime(t), nothing: mc.do_nothing[i], event: mc.with_event[i], best: mc.best_variant[i], p10: mc.p10?.[i], band: mc.p90 && mc.p10 ? mc.p90[i] - mc.p10[i] : undefined })) : []
  const label = card.proposed ? (card.proposed.label || card.proposed.type) : 'event'
  const canAdd = (card.verdict === 'approved' || card.verdict === 'approved_with_condition') && card.plan_events?.length
  const add = async () => {
    setBusy(true)
    try { await api.accept(card.plan_events); setAdded(true); onAccepted && onAccepted() } finally { setBusy(false) }
  }
  return (
    <div className="pcard">
      <div className="row">
        <span className={`badge ${card.verdict}`}>{VERDICT[card.verdict] || card.verdict}</span>
        <b>{label}</b>
        {card.proposed ? <span className="muted">{card.proposed.start_time.replace('T', ' ')}</span> : null}
        <span className="muted">confidence {card.confidence.toFixed(2)}</span>
      </div>
      {card.condition ? <div className="cond">{card.verdict === 'denied' ? 'Why: ' : 'Condition: '}{card.condition}</div> : null}
      {card.verdict !== 'request_data' && card.verdict !== 'escalate' ? (
        <div className="stats">
          <div><span className="muted">P(hypo)</span><b>{pct(card.p_hypo)}</b></div>
          <div><span className="muted">P(hyper)</span><b>{pct(card.p_hyper)}</b></div>
          <div><span className="muted">TIR</span><b>{pct(card.tir)}</b></div>
          <div><span className="muted">energy</span><b>{card.energy.toFixed(0)}</b></div>
        </div>
      ) : null}
      {mc && !compact ? (
        <ResponsiveContainer width="100%" height={150}>
          <ComposedChart data={data} margin={{ left: 0, right: 6, top: 4, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="t" tick={{ fontSize: 10, fill: 'var(--muted)' }} interval={Math.max(1, Math.floor(data.length / 6))} />
            <YAxis domain={[40, 300]} tick={{ fontSize: 10, fill: 'var(--muted)' }} width={30} />
            <Tooltip contentStyle={{ background: '#0b0f14', border: '1px solid var(--border)', fontSize: 11 }} />
            <ReferenceLine y={70} stroke="var(--red)" strokeDasharray="4 4" />
            <Area type="monotone" dataKey="p10" stackId="b" stroke="none" fill="transparent" isAnimationActive={false} />
            <Area type="monotone" dataKey="band" stackId="b" stroke="none" fill="var(--red)" fillOpacity={0.12} isAnimationActive={false} name="p10–p90 (as proposed)" />
            <Line type="monotone" dataKey="nothing" stroke="#8b98a8" dot={false} strokeDasharray="4 3" isAnimationActive={false} name="do nothing" />
            <Line type="monotone" dataKey="event" stroke="var(--red)" dot={false} strokeWidth={2} isAnimationActive={false} name="as proposed" />
            <Line type="monotone" dataKey="best" stroke="var(--green)" dot={false} strokeWidth={2} isAnimationActive={false} name="best variant" />
            <Legend wrapperStyle={{ fontSize: 10 }} />
          </ComposedChart>
        </ResponsiveContainer>
      ) : null}
      {card.factors?.length ? (
        <div className="factors">Top factors: {card.factors.map((f) => `${f.name} (${f.weight.toFixed(2)})`).join(' · ')}</div>
      ) : null}
      {card.long_term_delta && Object.keys(card.long_term_delta).length ? (
        <div className="factors">If repeated weekly, 10-year risk Δ (pp): {Object.entries(card.long_term_delta).map(([k, v]) => `${k.replace('dmg_', '')} ${v >= 0 ? '+' : ''}${v.toFixed(2)}`).join(' · ')}</div>
      ) : null}
      <div className="row" style={{ marginTop: 8 }}>
        {canAdd ? <button className="add" disabled={busy || added} onClick={add}>{added ? 'Added to plan' : `Add to plan${card.plan_events.length > 1 ? ` (${card.plan_events.length} events)` : ''}`}</button> : null}
        {onWhy ? <button className="link" onClick={onWhy}>/why</button> : null}
        <details>
          <summary>data used / missing · variants</summary>
          <div className="mono" style={{ marginTop: 6 }}>
            <div>used: {card.data_used.join('; ')}</div>
            <div>missing: {card.data_missing.join('; ')}</div>
            {card.variants?.length ? <table style={{ marginTop: 6 }}><thead><tr><th>scenario</th><th>condition</th><th className="num">P(hypo)</th><th className="num">min</th><th>ok</th></tr></thead>
              <tbody>{card.variants.map((v) => <tr key={v.name}><td>{v.name}</td><td>{v.condition}</td><td className="num">{pct(v.p_hypo)}</td><td className="num">{v.min_glucose}</td><td>{v.blocked ? 'blocked' : v.passes ? '✓' : '✗'}</td></tr>)}</tbody></table> : null}
          </div>
        </details>
      </div>
    </div>
  )
}
