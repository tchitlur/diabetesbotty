import React from 'react'
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'
import { fmtTime, pct, mgdl, num } from '../api.js'
import Status, { ChartBox } from './Status.jsx'
import { TICK, TIP, GRID, xLabel, yLabel, MARGIN, COLORS, legendFilter } from './chart.js'

const FAST = [
  ['glucose', 'Glucose', 0], ['plasma_insulin', 'Plasma insulin', 1], ['gut_carbs_1', 'Gut carbs, stomach', 0], ['gut_carbs_2', 'Gut carbs, absorbing', 0],
  ['liver_glycogen', 'Liver glycogen', 0], ['muscle_glycogen', 'Muscle glycogen', 0], ['blood_alcohol', 'Blood alcohol', 3], ['caffeine', 'Caffeine', 0],
  ['ketones', 'Ketones', 2], ['hydration', 'Hydration', 2],
]
const MEDIUM = [['sleep_debt', 'Sleep debt', 1], ['insulin_sensitivity', 'Insulin sensitivity', 2], ['training_load', 'Training load', 0], ['fat_mass', 'Fat mass', 1], ['lean_mass', 'Lean mass', 1], ['hba1c', 'HbA1c', 2]]

function Gauge({ value }) {
  const v = Math.max(0, Math.min(100, value || 0))
  const ang = Math.PI * (1 - v / 100)
  const r = 70, cx = 80, cy = 82
  const x = cx + r * Math.cos(ang), y = cy - r * Math.sin(ang)
  const color = v >= 70 ? COLORS.good : v >= 45 ? COLORS.warn : COLORS.bad
  return (
    <div className="gauge" title="Energy score 0–100 from |glucose − 100|, sleep debt, caffeine and hydration. Green ≥ 70, amber 45–69, red < 45.">
      <svg width="160" height="92" viewBox="0 0 160 92">
        <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} stroke="#1f2731" strokeWidth="14" fill="none" />
        <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${x} ${y}`} stroke={color} strokeWidth="14" fill="none" strokeLinecap="round" />
      </svg>
      <div className="val">{Math.round(v)}<small> / 100</small></div>
    </div>
  )
}

export default function NowTab({ state, forecast, history }) {
  const fc = forecast.data, hist = history.data
  const data = []
  if (hist) hist.times.forEach((t, i) => data.push({ t: fmtTime(t), actual: hist.glucose[i] }))
  if (fc) fc.times.forEach((t, i) => data.push({ t: fmtTime(t), median: fc.median[i], p10: fc.p10[i], band: fc.p90[i] - fc.p10[i] }))
  const sub = fc ? fc.times.map((t, i) => ({ t: fmtTime(t), insulin: fc.substances.insulin?.[i], alcohol: fc.substances.alcohol?.[i], caffeine: fc.substances.caffeine?.[i] })) : []
  const busy = forecast.loading || history.loading
  return (
    <div className="grid">
      <div className="grid three">
        <div className="card">
          <h3>Glucose now (estimated)</h3>
          <Status loading={!state} loadingText="Estimating state…">
            {state ? <>
              <div className="big">{mgdl(state.values.glucose)} ± {mgdl(state.std.glucose)}<span className="unit">mg/dL</span></div>
              <div className="note">Unscented Kalman filter over the last 12 h of CGM, as of {state.as_of.replace('T', ' ')}</div>
            </> : null}
          </Status>
        </div>
        <div className="card">
          <h3>Next 8 hours, doing nothing</h3>
          <Status loading={forecast.loading} error={forecast.error} loadingText="Running 200 Monte Carlo trajectories…">
            {fc ? <>
              <div className="kv">
                <span className="k">P(glucose &lt; 70)</span><b className="v">{pct(fc.p_hypo_8h)}</b><span />
                <span className="k">P(glucose &gt; 250)</span><b className="v">{pct(fc.p_hyper_8h)}</b><span />
                <span className="k">Time in range 70–180</span><b className="v">{pct(fc.tir)}</b><span />
              </div>
              <div className="note">200 trajectories sampled from the fitted parameter posterior, plus the residual model</div>
            </> : null}
          </Status>
        </div>
        <div className="card">
          <h3>Energy score</h3>
          <Status loading={!state}><Gauge value={state?.values.energy_score} /></Status>
        </div>
      </div>

      <div className="card">
        <h3>Glucose: last 6 h (CGM) and next 8 h (forecast median with p10–p90 band)</h3>
        <ChartBox loading={busy} error={forecast.error} height={280} loadingText="Running forecast…">
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={data} margin={MARGIN}>
              <CartesianGrid {...GRID} />
              <XAxis dataKey="t" tick={TICK} interval={11} label={xLabel('time (HH:MM)')} />
              <YAxis domain={[40, 300]} tick={TICK} width={46} label={yLabel('glucose (mg/dL)')} />
              <Tooltip contentStyle={TIP} formatter={(v, n) => [n === 'p10–p90 band' ? '' : `${Math.round(v)} mg/dL`, n]} />
              <ReferenceLine y={70} stroke={COLORS.bad} strokeDasharray="4 4" />
              <ReferenceLine y={180} stroke={COLORS.warn} strokeDasharray="4 4" />
              <ReferenceLine y={250} stroke={COLORS.bad} strokeDasharray="2 6" />
              <Area type="monotone" dataKey="p10" stackId="b" stroke="none" fill="transparent" isAnimationActive={false} legendType="none" tooltipType="none" />
              <Area type="monotone" dataKey="band" stackId="b" stroke="none" fill={COLORS.accent} fillOpacity={0.18} isAnimationActive={false} name="p10–p90 band" />
              <Line type="monotone" dataKey="actual" stroke={COLORS.cgm} dot={false} strokeWidth={1.5} isAnimationActive={false} name="CGM" connectNulls={false} />
              <Line type="monotone" dataKey="median" stroke={COLORS.accent} dot={false} strokeWidth={2} isAnimationActive={false} name="forecast median" />
              <Legend wrapperStyle={{ fontSize: 11, paddingTop: 12 }} formatter={legendFilter(['p10'])} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartBox>
        <div className="note">Dashed lines: 70 (low), 180 (high), 250 (hyper breach). Gaps in the CGM line are sensor dropouts.</div>
      </div>

      <div className="grid two">
        <div className="card">
          <h3>Active substances over the forecast (median)</h3>
          <ChartBox loading={forecast.loading} height={200}>
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={sub} margin={MARGIN}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="t" tick={TICK} interval={11} label={xLabel('time (HH:MM)')} />
                <YAxis yAxisId="l" tick={TICK} width={46} label={yLabel('insulin mU/L · caffeine mg')} />
                <YAxis yAxisId="r" orientation="right" tick={TICK} width={50} domain={[0, 0.15]} label={yLabel('alcohol g/dL', 'right')} />
                <Tooltip contentStyle={TIP} formatter={(v, n) => [n.startsWith('BAC') ? Number(v).toFixed(3) : Math.round(v), n]} />
                <Line yAxisId="l" type="monotone" dataKey="insulin" stroke={COLORS.accent} dot={false} name="plasma insulin (mU/L)" isAnimationActive={false} />
                <Line yAxisId="l" type="monotone" dataKey="caffeine" stroke={COLORS.s3} dot={false} name="caffeine (mg)" isAnimationActive={false} />
                <Line yAxisId="r" type="monotone" dataKey="alcohol" stroke={COLORS.s2} dot={false} name="BAC (g/dL)" isAnimationActive={false} />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 12 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </ChartBox>
        </div>
        <div className="card">
          <h3>Estimated state (± std for the fast layer)</h3>
          <Status loading={!state} loadingText="Estimating state…">
            {state ? <div className="kv">
              {FAST.map(([k, l, d]) => (
                <React.Fragment key={k}>
                  <span className="k">{l}</span>
                  <span className="v">{num(state.values[k], d)}{state.std[k] != null ? ` ± ${num(state.std[k], d)}` : ''}</span>
                  <span className="u">{state.units[k]}</span>
                </React.Fragment>
              ))}
              {MEDIUM.map(([k, l, d]) => (
                <React.Fragment key={k}>
                  <span className="k">{l}</span>
                  <span className="v">{num(state.values[k], d)}</span>
                  <span className="u">{state.units[k]}</span>
                </React.Fragment>
              ))}
            </div> : null}
          </Status>
          <div className="note">Medium-layer values (sleep debt onward) are daily estimates without a std.</div>
        </div>
      </div>
    </div>
  )
}
