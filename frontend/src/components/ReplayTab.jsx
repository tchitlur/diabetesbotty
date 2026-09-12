import React, { useEffect, useRef, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Legend } from 'recharts'
import { api, fmtTime, fmtDate, mgdl } from '../api.js'
import Status, { ChartBox } from './Status.jsx'
import { TICK, TIP, GRID, xLabel, yLabel, MARGIN, COLORS } from './chart.js'

// Replay a past day (quiet, inside "I'm nerdy"): what the sensor showed vs what the model says
// would have happened with more or less of what you logged.
export default function ReplayTab() {
  const [days, setDays] = useState(null)
  const [suggest, setSuggest] = useState(null)
  const [date, setDate] = useState('')
  const [carbs, setCarbs] = useState(1)
  const [alcohol, setAlcohol] = useState(1)
  const [exercise, setExercise] = useState(1)
  const [insulin, setInsulin] = useState(1)
  const [r, setR] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const timer = useRef(null)

  useEffect(() => {
    let alive = true
    Promise.all([api.replayDays(), api.replaySuggest().catch(() => null)]).then(([d, s]) => {
      if (!alive) return
      setDays(d)
      setSuggest(s?.suggested || null)
      const pick = s?.suggested?.date || [...d].reverse().find((x) => x.drinks > 0 && x.overnight_low)?.date || [...d].reverse().find((x) => x.drinks > 0)?.date || d[d.length - 1]?.date
      if (pick) setDate(pick)
    }).catch((e) => setErr(String(e.message)))
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (!date) return
    setBusy(true)
    clearTimeout(timer.current)
    let alive = true
    timer.current = setTimeout(() => {
      api.replay({ date, carbs_scale: carbs, alcohol_scale: alcohol, exercise_scale: exercise, insulin_scale: insulin })
        .then((x) => { if (alive) { setR(x); setErr(null) } }).catch((e) => alive && setErr(String(e.message))).finally(() => alive && setBusy(false))
    }, 250)
    return () => { alive = false }
  }, [date, carbs, alcohol, exercise, insulin])

  const data = r ? r.times.map((t, i) => ({ t: fmtTime(t), actual: r.actual[i], original: r.simulated_original[i], modified: r.simulated[i] })) : []
  const info = days?.find((d) => d.date === date)
  const modified = carbs !== 1 || alcohol !== 1 || exercise !== 1 || insulin !== 1
  return (
    <div className="grid">
      <div className="card">
        <h3>Replay a past day</h3>
        <Status loading={!days && !err} error={err && !days ? err : null} loadingText="Listing the days you can replay…">
          {days ? <>
            <div className="toolbar">
              <label>Day&nbsp;<select value={date} onChange={(e) => setDate(e.target.value)}>
                {days.map((d) => <option key={d.date} value={d.date}>{fmtDate(d.date)}{d.drinks ? ` · ${d.drinks} drinks` : ''}{d.exercise_min ? ` · ${Math.round(d.exercise_min)} min exercise` : ''}{d.overnight_low ? ' · overnight low' : ''}</option>)}
              </select></label>
              {info ? <span className="muted small">lowest overnight reading {info.overnight_min != null ? `${mgdl(info.overnight_min)} mg/dL` : 'unknown (sensor gap)'}</span> : null}
              <button className="small" onClick={() => { setCarbs(1); setAlcohol(1); setExercise(1); setInsulin(1) }} disabled={!modified}>reset sliders</button>
            </div>
            {suggest ? <div className="note">Try {fmtDate(suggest.date)} ({suggest.drinks} drinks): set Alcohol to 0 and the model's overnight low rises from {mgdl(suggest.overnight_min_as_logged)} to {mgdl(suggest.overnight_min_no_alcohol)} mg/dL.</div> : null}
            <div className="grid two" style={{ marginTop: 'var(--s2)' }}>
              <div>
                <div className="slider"><span>Carbs ×</span><input type="range" min="0" max="2" step="0.1" value={carbs} onChange={(e) => setCarbs(+e.target.value)} aria-label="carbs scale" /><b>{carbs.toFixed(1)}</b></div>
                <div className="slider"><span>Alcohol ×</span><input type="range" min="0" max="2" step="0.1" value={alcohol} onChange={(e) => setAlcohol(+e.target.value)} aria-label="alcohol scale" /><b>{alcohol.toFixed(1)}</b></div>
              </div>
              <div>
                <div className="slider"><span>Exercise ×</span><input type="range" min="0" max="2" step="0.1" value={exercise} onChange={(e) => setExercise(+e.target.value)} aria-label="exercise scale" /><b>{exercise.toFixed(1)}</b></div>
                <div className="slider"><span>Meal insulin ×</span><input type="range" min="0" max="1.5" step="0.1" value={insulin} onChange={(e) => setInsulin(+e.target.value)} aria-label="meal insulin scale" /><b>{insulin.toFixed(1)}</b></div>
              </div>
            </div>
            <ChartBox loading={busy} error={err} height={260} loadingText="Re-running the day…">
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={data} margin={{ ...MARGIN, bottom: 22 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="t" tick={TICK} interval={23} label={xLabel('time, 6 am through 8 am the next morning')} />
                  <YAxis domain={[40, 320]} tick={TICK} width={46} label={yLabel('glucose (mg/dL)')} />
                  <Tooltip contentStyle={TIP} formatter={(v, n) => [`${Math.round(v)} mg/dL`, n]} />
                  <ReferenceLine y={70} stroke={COLORS.bad} strokeDasharray="4 4" />
                  <ReferenceLine y={180} stroke={COLORS.warn} strokeDasharray="4 4" />
                  <Line type="monotone" dataKey="actual" stroke={COLORS.cgm} dot={false} strokeWidth={1.5} name="sensor" isAnimationActive={false} connectNulls={false} />
                  <Line type="monotone" dataKey="original" stroke={COLORS.accent} dot={false} strokeWidth={modified ? 1.5 : 2} strokeDasharray={modified ? '5 3' : undefined} name="model: as logged" isAnimationActive={false} />
                  {modified ? <Line type="monotone" dataKey="modified" stroke={COLORS.good} dot={false} strokeWidth={2} name="model: with sliders" isAnimationActive={false} /> : null}
                  <Legend wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
                </LineChart>
              </ResponsiveContainer>
            </ChartBox>
            {r ? (
              <div className="kv" style={{ marginTop: 'var(--s2)' }}>
                <span className="k">Model's lowest glucose</span><b className="v">{mgdl(r.min_glucose_original)} → {mgdl(r.min_glucose_modified)} mg/dL</b><span />
                <span className="k">Minutes below 70</span><b className="v">{Math.round(r.hypo_minutes_original)} → {Math.round(r.hypo_minutes_modified)} min</b><span />
              </div>
            ) : null}
            <div className="note">The model restarts from where you really were at 6 am and 6 pm, then runs on its own; the sliders scale that day's logged food, drinks, exercise and insulin (alcohol at 0 also removes the drinks' carbs).</div>
          </> : null}
        </Status>
      </div>
      <div className="card">
        <h3>Logged that day</h3>
        <Status loading={busy && !r} empty={r && r.events.filter((e) => !(e.type === 'insulin' && e.insulin_kind === 'basal')).length === 0} emptyText="Nothing logged on this day.">
          {r ? <table><thead><tr><th>time</th><th>what</th><th className="num">carbs (g)</th><th className="num">alcohol (g)</th><th className="num">insulin (U)</th><th className="num">minutes</th></tr></thead>
            <tbody>{r.events.filter((e) => !(e.type === 'insulin' && e.insulin_kind === 'basal')).map((e, i) => <tr key={i}><td>{fmtTime(e.start_time)}</td><td>{e.label || e.type}</td><td className="num">{e.carbs_g ? Math.round(e.carbs_g) : ''}</td><td className="num">{e.alcohol_g ? Math.round(e.alcohol_g) : ''}</td><td className="num">{e.insulin_units ? e.insulin_units.toFixed(1) : ''}</td><td className="num">{e.type === 'exercise' ? Math.round(e.duration_min) : ''}</td></tr>)}</tbody></table> : null}
        </Status>
      </div>
    </div>
  )
}
