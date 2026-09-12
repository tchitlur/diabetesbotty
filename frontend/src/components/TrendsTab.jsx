import React, { useEffect, useState } from 'react'
import { LineChart, Line, ScatterChart, Scatter, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Legend } from 'recharts'
import { api } from '../api.js'
import Status from './Status.jsx'
import { TICK, TIP, GRID, xLabel, yLabel, MARGIN, COLORS } from './chart.js'

const M = { ...MARGIN, bottom: 22 }

// Long-term trends (quiet, inside "I'm nerdy"): A1c estimate, how well insulin works vs sleep, lows per day.
export default function TrendsTab() {
  const [t, setT] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { let alive = true; api.trends().then((x) => alive && setT(x)).catch((e) => alive && setErr(String(e.message))); return () => { alive = false } }, [])
  const daily = t ? t.daily.map((r) => ({ ...r, d: r.date.slice(5), eff: Math.round(100 * r.insulin_sensitivity) })) : []
  const a1c = t ? [...daily.map((r) => ({ d: r.d, hba1c: r.hba1c })), ...t.a1c_projection.map((p) => ({ d: `+${p.day}d`, proj: p.hba1c }))] : []
  const scatter = daily.filter((r) => r.sleep_hours != null).map((r) => ({ x: r.sleep_hours, y: r.eff }))
  const wrap = (title, note, chart) => (
    <div className="card">
      <h3>{title}</h3>
      <Status loading={!t && !err} error={err} loadingText="Loading 90 days of daily estimates…">{t ? chart : null}</Status>
      {note ? <div className="note">{note}</div> : null}
    </div>
  )
  return (
    <div className="grid two">
      {wrap('HbA1c: estimate and 90-day projection', t ? `If your weeks stay like the last few, A1c settles near ${t.a1c_steady}%. Dashed amber line: the 7% target.` : '', (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={a1c} margin={M}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="d" tick={TICK} interval={13} label={xLabel('date (MM-DD), then days ahead')} />
            <YAxis domain={[5, 9]} tick={TICK} width={40} label={yLabel('HbA1c (%)')} />
            <Tooltip contentStyle={TIP} formatter={(v) => [`${Number(v).toFixed(2)} %`]} />
            <ReferenceLine y={7} stroke={COLORS.warn} strokeDasharray="4 4" />
            <Line type="monotone" dataKey="hba1c" stroke={COLORS.accent} dot={false} name="A1c estimate (%)" isAnimationActive={false} />
            <Line type="monotone" dataKey="proj" stroke={COLORS.s2} dot={false} strokeDasharray="5 3" name="projection (%)" isAnimationActive={false} />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
          </LineChart>
        </ResponsiveContainer>
      ))}
      {wrap('How well insulin worked, day by day', 'Compared with your usual (100%). A short night makes insulin work less well the next day.', (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={daily} margin={M}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="d" tick={TICK} interval={13} label={xLabel('date (MM-DD)')} />
            <YAxis yAxisId="l" domain={[60, 130]} tick={TICK} width={40} label={yLabel('insulin effect (% of usual)')} />
            <YAxis yAxisId="r" orientation="right" domain={[0, 6]} tick={TICK} width={40} label={yLabel('sleep debt (h)', 'right')} />
            <Tooltip contentStyle={TIP} formatter={(v, n) => [n.startsWith('sleep') ? `${Number(v).toFixed(1)} h` : `${Math.round(v)}%`, n]} />
            <ReferenceLine yAxisId="l" y={100} stroke={COLORS.s4} strokeDasharray="4 4" />
            <Line yAxisId="l" type="monotone" dataKey="eff" stroke={COLORS.good} dot={false} name="insulin effect (% of usual)" isAnimationActive={false} />
            <Line yAxisId="r" type="monotone" dataKey="sleep_debt" stroke={COLORS.s3} dot={false} name="sleep debt (h)" isAnimationActive={false} />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
          </LineChart>
        </ResponsiveContainer>
      ))}
      {wrap('Time below 70 mg/dL, hours per day', 'From the sensor record.', (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={daily} margin={M}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="d" tick={TICK} interval={13} label={xLabel('date (MM-DD)')} />
            <YAxis tick={TICK} width={40} label={yLabel('hours / day')} />
            <Tooltip contentStyle={TIP} formatter={(v) => [`${Number(v).toFixed(1)} h`, 'below 70']} />
            <Bar dataKey="hypo_hours" fill={COLORS.bad} isAnimationActive={false} name="hours below 70" />
          </BarChart>
        </ResponsiveContainer>
      ))}
      {wrap('Sleep vs how well insulin works', 'One point per day: last night’s sleep against the next day’s insulin effect.', (
        <ResponsiveContainer width="100%" height={200}>
          <ScatterChart margin={{ ...M, bottom: 26 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="x" type="number" domain={[4.5, 9.5]} tick={TICK} name="sleep" label={xLabel('sleep last night (h)')} />
            <YAxis dataKey="y" type="number" domain={[60, 130]} tick={TICK} width={40} name="effect" label={yLabel('insulin effect (%)')} />
            <Tooltip contentStyle={TIP} cursor={{ strokeDasharray: '3 3' }} formatter={(v, n) => [n === 'sleep' ? `${Number(v).toFixed(1)} h` : `${Math.round(v)}%`, n === 'sleep' ? 'sleep' : 'insulin effect']} />
            <Scatter data={scatter} fill={COLORS.accent} isAnimationActive={false} name="day" />
          </ScatterChart>
        </ResponsiveContainer>
      ))}
    </div>
  )
}
