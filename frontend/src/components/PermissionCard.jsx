import React, { useState } from 'react'
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'
import { api, fmtTime, fmtWhen, pct, mgdl, verdictTone } from '../api.js'
import { TICK, TIP, GRID, COLORS, legendFilter, xLabel, yLabel } from './chart.js'

const VERDICT = {
  approved: 'Approved', approved_with_condition: 'Approved with a condition', denied: 'Denied',
  request_data: 'Need data before deciding', escalate: 'Escalate to your care team',
}
const ORGAN = { dmg_eye: 'eyes', dmg_kidney: 'kidneys', dmg_nerve: 'nerves', dmg_cardio: 'heart', dmg_liver: 'liver' }

export default function PermissionCard({ card, compact = false, onAccepted, onWhy }) {
  const [added, setAdded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const tone = verdictTone(card.verdict)
  const mc = card.mini_curve
  const data = mc ? mc.times.map((t, i) => ({ t: fmtTime(t), nothing: mc.do_nothing[i], event: mc.with_event[i], best: mc.best_variant[i], p10: mc.p10?.[i], band: mc.p90 && mc.p10 ? mc.p90[i] - mc.p10[i] : undefined })) : []
  const label = card.proposed ? (card.proposed.label || card.proposed.type) : 'event'
  const canAdd = (card.verdict === 'approved' || card.verdict === 'approved_with_condition') && card.plan_events?.length
  const gated = card.verdict === 'request_data' || card.verdict === 'escalate'
  const add = async () => {
    setBusy(true); setErr(null)
    try { await api.accept(card.plan_events); setAdded(true); onAccepted && onAccepted() } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div className={`pcard ${tone}`}>
      <div className="verdict">{VERDICT[card.verdict] || card.verdict}</div>
      <div className="what"><b>{label}</b>{card.proposed ? <> · {fmtWhen(card.proposed.start_time)}</> : null}{!gated ? <> · confidence {pct(card.confidence)}</> : null}</div>
      {card.condition ? <div className="cond"><span className="lbl">{card.verdict === 'denied' ? 'Why:' : gated ? 'What is needed:' : 'Condition:'}</span>{card.condition}</div> : null}
      {gated ? (
        <div className="line">No simulation was run: the safety gate stopped before the decision ({card.gate?.reason}). {card.data_missing?.length ? `Missing: ${card.data_missing.join('; ')}.` : ''}</div>
      ) : (
        <>
          <div className="stats">
            <div title="Probability that glucose drops below 70 mg/dL within the horizon, under the best passing option">P(hypo)<b>{pct(card.p_hypo)}</b></div>
            <div title="Probability that glucose exceeds 250 mg/dL within the horizon">P(hyper)<b>{pct(card.p_hyper)}</b></div>
            <div title="Time in range 70–180 over the horizon">time in range<b>{pct(card.tir)}</b></div>
            <div title="Mean energy score 0–100 over the horizon">energy<b>{Math.round(card.energy)}</b></div>
          </div>
          {mc && !compact ? (
            <ResponsiveContainer width="100%" height={170}>
              <ComposedChart data={data} margin={{ left: 4, right: 10, top: 6, bottom: 14 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="t" tick={TICK} interval={Math.max(1, Math.floor(data.length / 6))} label={xLabel('time (HH:MM)')} />
                <YAxis domain={[40, 300]} tick={TICK} width={40} label={yLabel('mg/dL')} />
                <Tooltip contentStyle={TIP} formatter={(v, n) => [n === 'p10–p90 (as proposed)' ? '' : `${Math.round(v)} mg/dL`, n]} />
                <ReferenceLine y={70} stroke={COLORS.bad} strokeDasharray="4 4" />
                <Area type="monotone" dataKey="p10" stackId="b" stroke="none" fill="transparent" isAnimationActive={false} legendType="none" tooltipType="none" />
                <Area type="monotone" dataKey="band" stackId="b" stroke="none" fill={COLORS.bad} fillOpacity={0.12} isAnimationActive={false} name="p10–p90 (as proposed)" />
                <Line type="monotone" dataKey="nothing" stroke={COLORS.s4} dot={false} strokeDasharray="4 3" isAnimationActive={false} name="do nothing" />
                <Line type="monotone" dataKey="event" stroke={COLORS.bad} dot={false} strokeWidth={2} isAnimationActive={false} name="as proposed" />
                <Line type="monotone" dataKey="best" stroke={COLORS.good} dot={false} strokeWidth={2} isAnimationActive={false} name="best option" />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 10 }} formatter={legendFilter(['p10'])} />
              </ComposedChart>
            </ResponsiveContainer>
          ) : null}
          {card.factors?.length ? <div className="line"><b>Top factors:</b> {card.factors.map((f) => `${f.name} (${f.weight.toFixed(2)})`).join(' · ')}</div> : null}
          {card.long_term_delta && Object.keys(card.long_term_delta).length ? (
            <div className="line"><b>If repeated weekly, 10-year risk changes by:</b> {Object.entries(card.long_term_delta).map(([k, v]) => `${ORGAN[k] || k} ${v >= 0 ? '+' : ''}${v.toFixed(2)} pp`).join(' · ')}</div>
          ) : null}
        </>
      )}
      <div className="actions">
        {canAdd ? <button className="good small" disabled={busy || added} onClick={add}>{added ? 'Added to plan' : `Add to plan${card.plan_events.length > 1 ? ` (${card.plan_events.length} events)` : ''}`}</button> : null}
        {onWhy ? <button className="ghost small" onClick={onWhy}>/why</button> : null}
        {err ? <span className="err">{err}</span> : null}
        {!gated ? (
          <details>
            <summary>data used / missing · all options simulated</summary>
            <div className="line">used: {card.data_used.join('; ')}</div>
            <div className="line">missing: {card.data_missing.join('; ')}</div>
            {card.variants?.length ? <div className="tablewrap"><table><thead><tr><th>option</th><th>condition</th><th className="num">P(hypo)</th><th className="num">min mg/dL</th><th>passes</th></tr></thead>
              <tbody>{card.variants.map((v) => <tr key={v.name}><td>{v.name.replace(/_/g, ' ')}</td><td>{v.condition || '–'}</td><td className="num">{pct(v.p_hypo)}</td><td className="num">{mgdl(v.min_glucose)}</td><td>{v.blocked ? 'blocked by rule' : v.passes ? 'yes' : 'no'}</td></tr>)}</tbody></table></div> : null}
          </details>
        ) : null}
      </div>
    </div>
  )
}
