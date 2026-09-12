import React, { useEffect, useState } from 'react'
import { pct, riskTone, verdictTone, RISK_THRESHOLDS } from '../api.js'
import Status from './Status.jsx'
import OrganMap from './OrganMap.jsx'

const LABEL = { dmg_eye: 'Eyes (retinopathy)', dmg_kidney: 'Kidneys (nephropathy)', dmg_nerve: 'Nerves (neuropathy)', dmg_cardio: 'Heart (cardiovascular)', dmg_liver: 'Liver' }

export default function BodyTab({ state, baseline, pendingChange }) {
  const [mode, setMode] = useState('current')
  useEffect(() => { if (pendingChange) setMode('change') }, [pendingChange])
  const base = baseline.data ? baseline.data.organ_risk_baseline : null
  const risks = mode === 'change' && pendingChange ? pendingChange.organ_risk_change : base
  return (
    <div className="grid">
      <div className="card">
        <h3>
          10-year organ risk
          <span className="seg" style={{ marginLeft: 'var(--s2)' }}>
            <button className={mode === 'current' ? 'active' : ''} onClick={() => setMode('current')}>current lifestyle</button>
            <button className={mode === 'change' ? 'active' : ''} onClick={() => setMode('change')} disabled={!pendingChange} title={pendingChange ? '' : 'Run /change <name> in the chat first'}>pending change{pendingChange ? `: ${pendingChange.change}` : ''}</button>
          </span>
        </h3>
        <Status loading={baseline.loading && !base} error={baseline.error} loadingText="Simulating the current week for 30 days and 10 years…">
          {base ? (
            <div className="organs">
              <OrganMap risks={risks} title={mode === 'change' && pendingChange ? `with /change ${pendingChange.change}` : 'current lifestyle, repeated for 10 years'} />
              <div>
                {Object.keys(LABEL).map((k) => {
                  const v = risks ? risks[k] : null
                  const b = base ? base[k] : null
                  return (
                    <div className="organ-row" key={k}>
                      <div>{LABEL[k]}</div>
                      <div className="bar"><i className={riskTone(v)} style={{ width: `${Math.min(100, (v || 0) * 400)}%` }} /></div>
                      <div className="mono" style={{ textAlign: 'right' }}>{pct(v, 1)}</div>
                      <div className="mono" style={{ textAlign: 'right' }}>{mode === 'change' && b != null && v != null ? <span className={v - b > 0.00005 ? 'up' : v - b < -0.00005 ? 'down' : 'flat'}>{v - b >= 0 ? '+' : ''}{(100 * (v - b)).toFixed(2)} pp</span> : <span className="faint">baseline</span>}</div>
                    </div>
                  )
                })}
                <div className="note">Colours: {RISK_THRESHOLDS}. Bars are scaled so 25 % fills the track. Each accumulator is a cumulative hazard looped over a representative week for 10 years; P = 1 − exp(−hazard). Coefficients (DCCT/UKPDS) in <code>backend/engine/params.yaml</code>. Baseline A1c-equivalent {baseline.data.week_summary.baseline.a1c_equivalent.toFixed(2)} %.</div>
                <h3 style={{ marginTop: 'var(--s4)' }}>Hazard accumulated in the 13 weeks of data</h3>
                <Status loading={!state}>
                  {state ? <div className="kv">{Object.keys(LABEL).map((k) => <React.Fragment key={k}><span className="k">{LABEL[k]}</span><span className="v">{state.values[k].toFixed(4)}</span><span className="u">cumulative hazard</span></React.Fragment>)}</div> : null}
                </Status>
              </div>
            </div>
          ) : null}
        </Status>
      </div>
      {pendingChange ? (
        <div className={`pcard ${verdictTone(pendingChange.verdict)}`}>
          <div className="verdict">/change {pendingChange.change}: {pendingChange.verdict.replace(/_/g, ' ')}</div>
          <div className="what">{pendingChange.reason}</div>
        </div>
      ) : null}
    </div>
  )
}
