import React from 'react'
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ReferenceLine, ReferenceArea, ResponsiveContainer } from 'recharts'
import { fmtTime, fmtDate } from '../api.js'
import { TICK, TIP, COLORS } from './chart.js'

// The card that comes with a chat answer, by type. The permission card stays AnswerCard (unchanged);
// everything here is small, read-only, and drawn from the tool result in the payload.

const TOOL_LABEL = { get_current_state: 'current state', get_forecast: 'forecast', explain_now: 'why now', query_history: 'history',
  evaluate_action: 'permission engine', log_event: 'your log', plan_day: 'day planner', change_lifestyle: '30-day change', compare_to_average: 'average person', whatif: 'what-if simulation' }

// "checked: current state, forecast" under every answer: the answer came from the model, not the language model
export function ToolChips({ tools, router }) {
  const names = [...new Set(tools || [])]
  if (!names.length) return <div className="chips" data-testid="tool-chips"><span className="chip off">general answer, no model call</span></div>
  return (
    <div className="chips" data-testid="tool-chips">
      <span className="chip-label">checked:</span>
      {names.map((n) => <span key={n} className="chip">{TOOL_LABEL[n] || n}</span>)}
      {router ? <span className="chip-label faint">· routed by {router === 'gemini' ? 'Gemini' : 'the built-in reader'}</span> : null}
    </div>
  )
}

function MiniChart({ times, line, line2, p10, p90, height = 120, domain = [40, 300], nowIso, label1 = 'expected', label2 }) {
  if (!times || !times.length) return null
  const data = times.map((t, i) => ({ t: fmtTime(t), iso: t, a: line?.[i], b: line2?.[i], p10: p10?.[i], band: p90 && p10 && p90[i] != null && p10[i] != null ? p90[i] - p10[i] : undefined })).filter((d, i, arr) => i === 0 || arr[i - 1].iso !== d.iso)
  const step = Math.max(1, Math.round(data.length / 6))
  const multiDay = data.length > 1 && data[0].iso.slice(0, 10) !== data[data.length - 1].iso.slice(0, 10)
  const ticks = data.filter((_, i) => i % step === 0).map((d) => d.iso)   // keyed by the ISO time: unique even across days
  const fmt = (iso) => (multiDay ? `${fmtDate(iso).replace(/,.*/, '')} ${fmtTime(iso)}` : fmtTime(iso))
  const now = nowIso ? data.find((d) => d.iso >= nowIso.slice(0, 16)) : null
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ left: 0, right: 10, top: 10, bottom: 0 }}>
        <XAxis dataKey="iso" tick={TICK} ticks={ticks} interval={0} tickFormatter={fmt} />
        <YAxis domain={domain} tick={TICK} width={36} ticks={[70, 180]} />
        <Tooltip contentStyle={TIP} formatter={(v, n) => (n === 'likely range' ? [null, null] : [`${Math.round(v)} mg/dL`, n])} labelFormatter={(l) => `at ${fmt(l)}`} />
        <ReferenceArea y1={70} y2={180} fill={COLORS.range} fillOpacity={0.07} />
        <ReferenceLine y={70} stroke={COLORS.bad} strokeDasharray="3 3" />
        {now ? <ReferenceLine x={now.iso} stroke={COLORS.s4} strokeDasharray="2 2" /> : null}
        {p10 ? <Area type="monotone" dataKey="p10" stackId="b" stroke="none" fill="transparent" isAnimationActive={false} legendType="none" tooltipType="none" /> : null}
        {p10 ? <Area type="monotone" dataKey="band" stackId="b" stroke="none" fill={COLORS.accent} fillOpacity={0.15} isAnimationActive={false} name="likely range" /> : null}
        <Line type="monotone" dataKey="a" stroke={COLORS.accent} dot={false} strokeWidth={2} isAnimationActive={false} name={label1} connectNulls={false} />
        {line2 ? <Line type="monotone" dataKey="b" stroke={COLORS.s3} dot={false} strokeWidth={2} strokeDasharray="5 3" isAnimationActive={false} name={label2 || 'what if'} /> : null}
      </ComposedChart>
    </ResponsiveContainer>
  )
}

export function StateCard({ p }) {
  const tone = p.position === 'in range' ? 'good' : p.position === 'low' ? 'bad' : 'warn'
  return (
    <div className="ccard" data-testid="card-state">
      <div className="ccard-head"><span className={`big ${tone}`}>{p.glucose}</span><span className="muted">mg/dL · {p.trend} {p.trend_arrow} · as of {p.as_of_text}</span></div>
      <div className="tile-strip">
        {(p.tiles || []).slice(0, 6).map((t) => <div key={t.key} className={`mini-tile ${t.tone}`}><span className="k">{t.label}</span><b>{t.value_text}</b><span className="s">{t.status}</span></div>)}
      </div>
    </div>
  )
}

export function ForecastCard({ p, nowIso }) {
  const isWhatIf = p.kind === 'whatif'
  const base = isWhatIf ? p.baseline : p
  const scen = isWhatIf ? p.scenario : null
  return (
    <div className="ccard" data-testid={isWhatIf ? 'card-whatif' : 'card-forecast'}>
      <div className="ccard-head">
        {isWhatIf ? <span className="muted">as usual (solid) vs what if (dashed), next {p.hours} h</span>
          : <><span className="big">{p.expected_at_end}</span><span className="muted">mg/dL expected by {p.to_text} · low {p.low.value} at {p.low.time_text} · peak {p.peak.value} at {p.peak.time_text}</span></>}
      </div>
      <MiniChart times={p.times} line={base.median} line2={scen ? scen.median : null} p10={isWhatIf ? null : p.p10} p90={isWhatIf ? null : p.p90} nowIso={nowIso} label1={isWhatIf ? 'as usual' : 'expected'} label2="what if" />
      <div className="kvs">
        {isWhatIf ? <>
          <span>low as usual <b>{base.low.value}</b> at {base.low.time_text}</span><span>low what-if <b>{scen.low.value}</b> at {scen.low.time_text}</span>
          <span>chance of a low <b>{base.p_low_pct}% → {scen.p_low_pct}%</b></span>
        </> : <>
          <span>chance of a low <b>{p.p_low_pct}%</b> ({p.p_low_word})</span><span>chance of a high <b>{p.p_high_pct}%</b></span><span>likely range at the end <b>{p.range_at_end[0]}–{p.range_at_end[1]}</b></span>
        </>}
      </div>
    </div>
  )
}

export function ExplainCard({ p }) {
  const max = Math.max(...p.terms.map((t) => Math.abs(t.mgdl_per_hour)), 1)
  const pend = p.pending
  return (
    <div className="ccard" data-testid="card-explain">
      <div className="ccard-head"><span className="big">{p.model_rate_mgdl_per_hour > 0 ? '+' : ''}{p.model_rate_mgdl_per_hour}</span><span className="muted">mg/dL per hour net, {p.direction} · sensor {p.sensor_rate_mgdl_per_hour > 0 ? '+' : ''}{p.sensor_rate_mgdl_per_hour}/h</span></div>
      <div className="bars">
        {p.terms.map((t) => (
          <div key={t.key} className="bar-row" title={t.detail}>
            <span className="k">{t.label}</span>
            <span className="track"><span className="mid" /><i className={t.mgdl_per_hour >= 0 ? 'pos' : 'neg'} style={t.mgdl_per_hour >= 0 ? { left: '50%', width: `${50 * Math.abs(t.mgdl_per_hour) / max}%` } : { right: '50%', width: `${50 * Math.abs(t.mgdl_per_hour) / max}%` }} /></span>
            <b className={t.mgdl_per_hour >= 0 ? 'good' : 'bad'}>{t.mgdl_per_hour > 0 ? '+' : ''}{t.mgdl_per_hour}</b>
          </div>
        ))}
      </div>
      <div className="kvs" data-testid="explain-pending">
        <span>carbs still digesting <b data-testid="pending-carbs">{pend.carbs_g} g</b>{pend.carbs_peak_in_min ? ` · fastest in ${pend.carbs_peak_in_min} min` : ''}{pend.carbs_done_in_min ? ` · done in ~${pend.carbs_done_in_min} min` : ''}</span>
        <span>insulin still to act <b>{pend.insulin_on_board_u} U</b>{pend.insulin_peaked_already ? ' · peaking now' : ` · peaks in ${pend.insulin_peak_in_min} min`}</span>
        {pend.last_meal ? <span>last meal {pend.last_meal.label} ({pend.last_meal.carbs_g} g) at {pend.last_meal.time_text}{pend.assumed_meal ? ' · assumed, not logged' : ''}</span> : null}
        {pend.last_bolus ? <span>last dose {pend.last_bolus.units} U at {pend.last_bolus.time_text}</span> : null}
      </div>
    </div>
  )
}

export function HistoryCard({ p }) {
  const s = p.series || {}
  const hasSeries = s.times && s.times.length > 2
  return (
    <div className="ccard" data-testid="card-history">
      <div className="ccard-head"><span className="muted">{p.start_text} → {p.end_text}</span></div>
      {hasSeries ? <MiniChart times={s.times} line={s.values} height={110} domain={[40, 300]} label1="sensor" /> : null}
      <div className="kvs">
        {p.average != null ? <span>average <b>{p.average}</b></span> : null}
        {p.time_in_range_pct != null ? <span>in range <b>{p.time_in_range_pct}%</b></span> : null}
        <span>lows <b>{p.n_lows}</b>{p.last_low ? ` · last ${p.last_low_when}, ${p.last_low.min}` : ''}</span>
        {p.totals && (p.totals.meals || p.totals.carbs_g) ? <span>logged <b>{p.totals.carbs_g} g carbs</b> over {p.totals.meals} meals{p.totals.exercise_min ? `, ${p.totals.exercise_min} min exercise` : ''}</span> : null}
        {p.sleep && p.sleep.length ? <span>sleep <b>{p.sleep[p.sleep.length - 1].hours} h</b> ({p.sleep[p.sleep.length - 1].bed_text} → {p.sleep[p.sleep.length - 1].wake_text})</span> : null}
      </div>
      {p.metric === 'events' && p.events?.length ? <ul className="ev-list">{p.events.slice(0, 10).map((e, i) => <li key={i}><span className="muted">{e.time_text}</span> {e.label}{e.carbs_g ? ` · ${e.carbs_g} g` : ''}{e.insulin_units ? ` · ${e.insulin_units} U` : ''}{e.type === 'exercise' ? ` · ${e.duration_min} min` : ''}</li>)}</ul> : null}
    </div>
  )
}

export function LoggedCard({ p }) {
  const st = p.state || {}
  return (
    <div className="ccard logged" data-testid="card-logged">
      <div className="ccard-head"><span className="pill good">logged</span><b>{p.phrase}</b><span className="muted">{p.when}</span></div>
      <div className="tile-strip">
        <div className="mini-tile good"><span className="k">Glucose</span><b>{st.glucose} mg/dL</b><span className="s">{st.trend}</span></div>
        {(st.tiles || []).slice(0, 4).map((t) => <div key={t.key} className={`mini-tile ${t.tone}`}><span className="k">{t.label}</span><b>{t.value_text}</b><span className="s">{t.status}</span></div>)}
      </div>
    </div>
  )
}

export function TextCard({ p }) {
  if (!p || !p.personal) return null
  return (
    <div className="ccard" data-testid="card-compare">
      <div className="kvs"><span>you: <b>{p.personal.headline}</b> ({p.personal.p_low_pct}%)</span><span>average person: <b>{p.population.headline}</b> ({p.population.p_low_pct}%)</span></div>
    </div>
  )
}

export { MiniChart }
