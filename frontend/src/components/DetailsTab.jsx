import React, { useEffect, useState } from 'react'
import { ComposedChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'
import { api, fmtTime, fmtDate, pct, likely, num } from '../api.js'
import Status, { ChartBox } from './Status.jsx'
import { TICK, TIP, GRID, xLabel, yLabel, MARGIN, COLORS } from './chart.js'
import ReplayTab from './ReplayTab.jsx'
import TrendsTab from './TrendsTab.jsx'

// Details: for people who want more than Home. Numbers, the decay of what is in the body,
// forecast chances, data quality and the model's sync status, your settings. "I'm nerdy" at the bottom.
export default function DetailsTab({ profile, parser, health, home }) {
  const [fc, setFc] = useState(null)
  const [state, setState] = useState(null)
  const [drift, setDrift] = useState(null)
  const [twin, setTwin] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    let alive = true
    Promise.all([api.forecast(480), api.state(), api.drift(), api.twinSummary()]).then(([f, s, d, t]) => { if (alive) { setFc(f); setState(s); setDrift(d); setTwin(t) } }).catch((e) => alive && setErr(String(e.message)))
    return () => { alive = false }
  }, [profile?.id])
  const sub = fc ? fc.times.map((t, i) => ({ t: fmtTime(t), insulin: fc.substances.insulin?.[i], alcohol: fc.substances.alcohol?.[i], caffeine: fc.substances.caffeine?.[i] })) : []
  const tiles = home.data?.tiles || []
  const sync = drift ? (drift.days_flagged >= 5 ? ['bad', 'needs a check'] : drift.flagged ? ['warn', 'drifting'] : ['good', 'in sync']) : ['off', 'checking…']
  const q = state?.data_quality
  return (
    <>
      <div className="card" data-testid="your-twin">
        <h3>Your twin</h3>
        <Status loading={!twin && !err} error={err} loadingText="Comparing your fit with the average…">
          {twin ? <>
            <div className="twin-rows">
              {twin.lines.map((l) => (
                <div key={l.key} className="twin-row">
                  <span className="text">{l.text}</span>
                  <span className="track" title={`${l.ratio}x the average`}><i className="mid" /><i className="dot" style={{ left: `${Math.round(100 * l.pos)}%` }} /></span>
                </div>
              ))}
            </div>
            <div className="note">{twin.learned}. The marker shows where you sit against the average person with T1D (centre = average; the ends = half or double).</div>
          </> : null}
        </Status>
      </div>

      <div className="grid two">
        <div className="card">
          <h3>Right now, in numbers</h3>
          <Status loading={home.loading && !home.data} error={home.error} loadingText="Loading…">
            {home.data ? <div className="numgrid" style={{ gridTemplateColumns: '1fr 1fr' }}>
              <div><span>Glucose</span><b>{home.data.glucose.value} ± {home.data.glucose.std} mg/dL</b></div>
              {tiles.map((t) => <div key={t.key}><span>{t.label}</span><b>{t.value_text}</b></div>)}
            </div> : null}
          </Status>
        </div>
        <div className="card">
          <h3>Next 8 hours, if you change nothing</h3>
          <Status loading={!fc && !err} error={err} loadingText="Running the forecast…">
            {fc ? <div className="kv">
              <span className="k">Chance of a low (under 70 mg/dL)</span><b className="v">{pct(fc.p_hypo_8h)}</b><span className="u">{likely(fc.p_hypo_8h)}</span>
              <span className="k">Chance of a high (over 250 mg/dL)</span><b className="v">{pct(fc.p_hyper_8h)}</b><span className="u">{likely(fc.p_hyper_8h)}</span>
              <span className="k">Time in range (70–180 mg/dL)</span><b className="v">{pct(fc.tir)}</b><span className="u">of the next 8 h</span>
            </div> : null}
          </Status>
          <div className="note">From 200 possible futures the model runs for your body, using its uncertainty about you and about the amounts you logged.</div>
        </div>
      </div>

      <div className="card">
        <h3>What is still in your body, next 8 hours</h3>
        <ChartBox loading={!fc && !err} error={err} height={220} loadingText="Running the forecast…">
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={sub} margin={MARGIN}>
              <CartesianGrid {...GRID} />
              <XAxis dataKey="t" tick={TICK} interval={11} label={xLabel('time')} />
              <YAxis yAxisId="l" tick={TICK} width={46} label={yLabel('insulin · caffeine')} />
              <YAxis yAxisId="r" orientation="right" tick={TICK} width={50} domain={[0, 0.15]} label={yLabel('alcohol (% BAC)', 'right')} />
              <Tooltip contentStyle={TIP} formatter={(v, n) => [n.startsWith('alcohol') ? Number(v).toFixed(3) : Math.round(v), n]} />
              <Line yAxisId="l" type="monotone" dataKey="insulin" stroke={COLORS.accent} dot={false} name="insulin in your blood (mU/L)" isAnimationActive={false} />
              <Line yAxisId="l" type="monotone" dataKey="caffeine" stroke={COLORS.s3} dot={false} name="caffeine (mg)" isAnimationActive={false} />
              <Line yAxisId="r" type="monotone" dataKey="alcohol" stroke={COLORS.s2} dot={false} name="alcohol (% BAC)" isAnimationActive={false} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartBox>
      </div>

      <div className="grid two">
        <div className="card">
          <h3>Sensor, data and model</h3>
          <Status loading={!state && !err} error={err}>
            {state ? <div className="kv">
              <span className="k">Last sensor reading</span><b className="v">{Math.round(state.staleness_min)} min ago</b><span className="u">advice stops after 20 min</span>
              <span className="k">Sensor data quality</span><b className={`v ${q >= 0.7 ? 'good' : q >= 0.4 ? 'warn' : 'bad'}`}>{pct(q)}</b><span className="u">coverage and clean readings, last 24 h and overall</span>
              <span className="k">Model sync with your sensor</span><b className={`v ${sync[0]}`}>{sync[1]}</b><span className="u">{drift ? (drift.flagged ? `errors rising for ${drift.days_flagged} day(s)` : 'its 1-hour forecasts still match your sensor') : ''}</span>
              <span className="k">Text and photo reader</span><b className="v">{parser ? (parser.gemini_configured ? `Gemini (${parser.model})` : 'built-in reader (no key)') : '…'}</b><span className="u">{parser?.last_parser ? `last used: ${parser.last_parser === 'gemini' ? 'Gemini' : 'built-in'}` : ''}</span>
              <span className="k">Latest reading</span><b className="v">{health ? `${fmtDate(health.now)} ${fmtTime(health.now)}` : '…'}</b><span className="u">the data follows the real clock</span>
            </div> : null}
          </Status>
        </div>
        <div className="card">
          <h3>Your settings</h3>
          <div className="kv">
            <span className="k">Name</span><b className="v">{profile.name}</b><span />
            <span className="k">Age · sex</span><b className="v">{profile.age} · {profile.sex === 'F' ? 'female' : profile.sex === 'M' ? 'male' : 'other'}</b><span />
            <span className="k">Weight · height</span><b className="v">{num(profile.weight_kg, 1)} kg · {Math.round(profile.height_cm)} cm</b><span />
            <span className="k">Carb ratio</span><b className="v">1 unit per {num(profile.carb_ratio_g_per_u, 1)} g carbs</b><span />
            <span className="k">Correction factor</span><b className="v">1 unit lowers {Math.round(profile.correction_factor_mgdl_per_u)} mg/dL</b><span />
            <span className="k">Target range</span><b className="v">{Math.round(profile.target_low)}–{Math.round(profile.target_high)} mg/dL</b><span />
            <span className="k">Data</span><b className="v">virtual person {profile.patient_id}</b><span className="u">90 days of sensor data</span>
          </div>
        </div>
      </div>

      <details className="nerdy">
        <summary>I'm nerdy — replay a past day, long-term trends</summary>
        <div className="quiet">
          <ReplayTab />
          <TrendsTab />
        </div>
      </details>
    </>
  )
}
