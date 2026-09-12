import React, { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Legend } from 'recharts'
import { api, fmtTime } from '../api.js'

export default function ReplayTab() {
  const [days, setDays] = useState([])
  const [date, setDate] = useState('')
  const [carbs, setCarbs] = useState(1)
  const [alcohol, setAlcohol] = useState(1)
  const [exercise, setExercise] = useState(1)
  const [insulin, setInsulin] = useState(1)
  const [r, setR] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const [suggest, setSuggest] = useState(null)
  const [touched, setTouched] = useState(false)
  useEffect(() => {
    api.replayDays().then((d) => {
      setDays(d)
      const pick = [...d].reverse().find((x) => x.drinks > 0 && x.overnight_low) || [...d].reverse().find((x) => x.drinks > 0) || d[d.length - 1]
      if (pick) setDate(pick.date)
    }).catch((e) => setErr(String(e.message)))
    // the backend checks recent drink nights for the one where removing alcohol lifts the low; switch to it unless the user already chose
    api.replaySuggest().then((s) => { setSuggest(s.suggested); if (s.suggested && !touched) setDate(s.suggested.date) }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!date) return
    let alive = true
    setBusy(true)
    api.replay({ date, carbs_scale: carbs, alcohol_scale: alcohol, exercise_scale: exercise, insulin_scale: insulin })
      .then((x) => { if (alive) { setR(x); setErr(null) } }).catch((e) => setErr(String(e.message))).finally(() => alive && setBusy(false))
    return () => { alive = false }
  }, [date, carbs, alcohol, exercise, insulin])

  const data = r ? r.times.map((t, i) => ({ t: fmtTime(t), actual: r.actual[i], original: r.simulated_original[i], modified: r.simulated[i] })) : []
  const info = days.find((d) => d.date === date)
  return (
    <div className="grid" style={{ gridTemplateColumns: '1fr' }}>
      <div className="card">
        <h3>Replay a past day {busy ? <span className="spinner" /> : null}</h3>
        <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
          <label>Day <select value={date} onChange={(e) => { setTouched(true); setDate(e.target.value) }}>
            {days.map((d) => <option key={d.date} value={d.date}>{d.date} {d.weekday}{d.drinks ? ` · ${d.drinks} drinks` : ''}{d.exercise_min ? ` · ${d.exercise_min.toFixed(0)} min exercise` : ''}{d.overnight_low ? ' · overnight LOW' : ''}</option>)}
          </select></label>
          {info ? <span className="muted">actual overnight min {info.overnight_min ?? '–'} mg/dL</span> : null}
          {suggest ? <span className="muted">· try {suggest.date} ({suggest.weekday}, {suggest.drinks} drinks): alcohol → 0 lifts the twin's overnight low {suggest.overnight_min_as_logged} → {suggest.overnight_min_no_alcohol}</span> : null}
          <button onClick={() => { setCarbs(1); setAlcohol(1); setExercise(1); setInsulin(1) }}>reset sliders</button>
        </div>
        <div className="grid two" style={{ marginTop: 8 }}>
          <div>
            <div className="slider"><span>Carbs ×</span><input type="range" min="0" max="2" step="0.1" value={carbs} onChange={(e) => setCarbs(+e.target.value)} /><b>{carbs.toFixed(1)}</b></div>
            <div className="slider"><span>Alcohol ×</span><input type="range" min="0" max="2" step="0.1" value={alcohol} onChange={(e) => setAlcohol(+e.target.value)} /><b>{alcohol.toFixed(1)}</b></div>
          </div>
          <div>
            <div className="slider"><span>Exercise ×</span><input type="range" min="0" max="2" step="0.1" value={exercise} onChange={(e) => setExercise(+e.target.value)} /><b>{exercise.toFixed(1)}</b></div>
            <div className="slider"><span>Bolus insulin ×</span><input type="range" min="0" max="1.5" step="0.1" value={insulin} onChange={(e) => setInsulin(+e.target.value)} /><b>{insulin.toFixed(1)}</b></div>
          </div>
        </div>
        {err ? <div className="err">{err}</div> : null}
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data} margin={{ left: 0, right: 10, top: 8, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="t" tick={{ fontSize: 10, fill: 'var(--muted)' }} interval={23} />
            <YAxis domain={[40, 320]} tick={{ fontSize: 10, fill: 'var(--muted)' }} width={34} />
            <Tooltip contentStyle={{ background: '#0b0f14', border: '1px solid var(--border)', fontSize: 11 }} />
            <ReferenceLine y={70} stroke="var(--red)" strokeDasharray="4 4" />
            <ReferenceLine y={180} stroke="var(--amber)" strokeDasharray="4 4" />
            <Line type="monotone" dataKey="actual" stroke="#e6edf3" dot={false} strokeWidth={1.5} name="actual CGM" isAnimationActive={false} connectNulls={false} />
            <Line type="monotone" dataKey="original" stroke="var(--accent)" dot={false} strokeDasharray="5 3" name="twin: as logged" isAnimationActive={false} />
            <Line type="monotone" dataKey="modified" stroke="var(--green)" dot={false} strokeWidth={2} name="twin: with sliders" isAnimationActive={false} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
          </LineChart>
        </ResponsiveContainer>
        {r ? (
          <div className="kv" style={{ marginTop: 6 }}>
            <span className="k">Twin min glucose</span><b>{r.min_glucose_original.toFixed(0)} → {r.min_glucose_modified.toFixed(0)} mg/dL</b><span />
            <span className="k">Minutes below 70</span><b>{r.hypo_minutes_original.toFixed(0)} → {r.hypo_minutes_modified.toFixed(0)}</b><span />
          </div>
        ) : null}
        <div className="sub" style={{ marginTop: 6 }}>06:00 through 08:00 next morning. The twin is re-anchored on its filtered state at 06:00 and 18:00; sliders scale that day's logged events.</div>
      </div>
      {r ? (
        <div className="card">
          <h3>Logged events that day</h3>
          <table><thead><tr><th>time</th><th>event</th><th className="num">carbs g</th><th className="num">alcohol g</th><th className="num">insulin U</th><th className="num">min</th></tr></thead>
            <tbody>{r.events.filter((e) => !(e.type === 'insulin' && e.insulin_kind === 'basal')).map((e, i) => <tr key={i}><td>{fmtTime(e.start_time)}</td><td>{e.label || e.type}</td><td className="num">{e.carbs_g ? e.carbs_g.toFixed(0) : ''}</td><td className="num">{e.alcohol_g ? e.alcohol_g.toFixed(0) : ''}</td><td className="num">{e.insulin_units ? e.insulin_units.toFixed(1) : ''}</td><td className="num">{e.type === 'exercise' ? e.duration_min.toFixed(0) : ''}</td></tr>)}</tbody></table>
        </div>
      ) : null}
    </div>
  )
}
