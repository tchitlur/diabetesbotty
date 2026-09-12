import React from 'react'
import { LineChart, Line, ScatterChart, Scatter, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Legend } from 'recharts'
import Status from './Status.jsx'
import { TICK, TIP, GRID, xLabel, yLabel, MARGIN, COLORS } from './chart.js'

const M = { ...MARGIN, bottom: 22 }

export default function TrendsTab({ trends }) {
  const t = trends.data
  const daily = t ? t.daily.map((r) => ({ ...r, d: r.date.slice(5) })) : []
  const a1c = t ? [...daily.map((r) => ({ d: r.d, hba1c: r.hba1c })), ...t.a1c_projection.map((p) => ({ d: `+${p.day}d`, proj: p.hba1c }))] : []
  const scatter = daily.filter((r) => r.sleep_hours != null).map((r) => ({ x: r.sleep_hours, y: r.insulin_sensitivity }))
  const wrap = (title, note, chart) => (
    <div className="card">
      <h3>{title}</h3>
      <Status loading={trends.loading} error={trends.error} loadingText="Loading 90 days of daily estimates…">{t ? chart : null}</Status>
      {note ? <div className="note">{note}</div> : null}
    </div>
  )
  return (
    <div className="grid two">
      {wrap('HbA1c: twin estimate and 90-day projection', t ? `Steady-state A1c for the current mean glucose: ${t.a1c_steady} %. Dashed amber line: 7 % target.` : '', (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={a1c} margin={M}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="d" tick={TICK} interval={13} label={xLabel('date (MM-DD) · then days ahead')} />
            <YAxis domain={[5, 9]} tick={TICK} width={40} label={yLabel('HbA1c (%)')} />
            <Tooltip contentStyle={TIP} formatter={(v) => [`${Number(v).toFixed(2)} %`]} />
            <ReferenceLine y={7} stroke={COLORS.warn} strokeDasharray="4 4" />
            <Line type="monotone" dataKey="hba1c" stroke={COLORS.accent} dot={false} name="A1c estimate (%)" isAnimationActive={false} />
            <Line type="monotone" dataKey="proj" stroke={COLORS.s2} dot={false} strokeDasharray="5 3" name="projection under the current week (%)" isAnimationActive={false} />
            <Legend wrapperStyle={{ fontSize: 11, paddingTop: 12 }} />
          </LineChart>
        </ResponsiveContainer>
      ))}
      {wrap('Insulin sensitivity and sleep debt, daily', 'Effective sensitivity multiplier (1.0 = the fitted baseline) after the sleep-debt effect; a short night lowers it the next day.', (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={daily} margin={M}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="d" tick={TICK} interval={13} label={xLabel('date (MM-DD)')} />
            <YAxis yAxisId="l" domain={[0.6, 1.3]} tick={TICK} width={40} label={yLabel('sensitivity (×)')} />
            <YAxis yAxisId="r" orientation="right" domain={[0, 6]} tick={TICK} width={40} label={yLabel('sleep debt (h)', 'right')} />
            <Tooltip contentStyle={TIP} formatter={(v, n) => [Number(v).toFixed(2), n]} />
            <ReferenceLine yAxisId="l" y={1} stroke={COLORS.s4} strokeDasharray="4 4" />
            <Line yAxisId="l" type="monotone" dataKey="insulin_sensitivity" stroke={COLORS.good} dot={false} name="sensitivity (×)" isAnimationActive={false} />
            <Line yAxisId="r" type="monotone" dataKey="sleep_debt" stroke={COLORS.s3} dot={false} name="sleep debt (h)" isAnimationActive={false} />
            <Legend wrapperStyle={{ fontSize: 11, paddingTop: 12 }} />
          </LineChart>
        </ResponsiveContainer>
      ))}
      {wrap('Hypoglycaemia: hours per day below 70 mg/dL', 'From the CGM record, valid readings only.', (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={daily} margin={M}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="d" tick={TICK} interval={13} label={xLabel('date (MM-DD)')} />
            <YAxis tick={TICK} width={40} label={yLabel('hours / day')} />
            <Tooltip contentStyle={TIP} formatter={(v) => [`${Number(v).toFixed(1)} h`, 'below 70']} />
            <Bar dataKey="hypo_hours" fill={COLORS.bad} isAnimationActive={false} name="hours below 70" />
          </BarChart>
        </ResponsiveContainer>
      ))}
      {wrap('Sleep vs insulin sensitivity', 'One point per day: last night’s sleep against the next day’s effective sensitivity.', (
        <ResponsiveContainer width="100%" height={220}>
          <ScatterChart margin={{ ...M, bottom: 26 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="x" type="number" domain={[4.5, 9.5]} tick={TICK} name="sleep" label={xLabel('sleep last night (h)')} />
            <YAxis dataKey="y" type="number" domain={[0.6, 1.3]} tick={TICK} width={40} name="sensitivity" label={yLabel('sensitivity (×)')} />
            <Tooltip contentStyle={TIP} cursor={{ strokeDasharray: '3 3' }} formatter={(v, n) => [Number(v).toFixed(2), n === 'sleep' ? 'sleep (h)' : 'sensitivity (×)']} />
            <Scatter data={scatter} fill={COLORS.accent} isAnimationActive={false} name="day" />
          </ScatterChart>
        </ResponsiveContainer>
      ))}
    </div>
  )
}
