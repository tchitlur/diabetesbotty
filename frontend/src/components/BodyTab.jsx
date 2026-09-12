import React, { useEffect, useState } from 'react'
import { api, pct } from '../api.js'
import OrganMap, { riskColor } from './OrganMap.jsx'

const LABEL = { dmg_eye: 'Eyes (retinopathy)', dmg_kidney: 'Kidneys (nephropathy)', dmg_nerve: 'Nerves (neuropathy)', dmg_cardio: 'Heart (cardiovascular)', dmg_liver: 'Liver' }

export default function BodyTab({ state, pendingChange }) {
  const [mode, setMode] = useState('current')
  const [baseline, setBaseline] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    // "current lifestyle" 10-year risks = the no_change request (same engine as a real change)
    api.change('no_change').then((r) => setBaseline(r)).catch((e) => setErr(String(e.message)))
  }, [])
  useEffect(() => { if (pendingChange) setMode('change') }, [pendingChange])
  const risks = mode === 'change' && pendingChange ? pendingChange.organ_risk_change : (baseline ? baseline.organ_risk_baseline : null)
  const base = baseline ? baseline.organ_risk_baseline : null
  const strain = state ? Object.fromEntries(Object.keys(LABEL).map((k) => [k, state.values[k]])) : null
  return (
    <div className="grid" style={{ gridTemplateColumns: '1fr' }}>
      <div className="card">
        <div className="row" style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <h3 style={{ margin: 0 }}>10-year organ risk</h3>
          <div className="toggle">
            <button className={mode === 'current' ? 'active' : ''} onClick={() => setMode('current')}>current lifestyle</button>
            <button className={mode === 'change' ? 'active' : ''} onClick={() => setMode('change')} disabled={!pendingChange} title={pendingChange ? '' : 'run /change <name> in the chat first'}>pending change{pendingChange ? `: ${pendingChange.change}` : ''}</button>
          </div>
        </div>
        {err ? <div className="err">{err}</div> : null}
        <div className="organs" style={{ marginTop: 12 }}>
          <OrganMap risks={risks} title={mode === 'change' && pendingChange ? `with /change ${pendingChange.change}` : 'current lifestyle, repeated for 10 years'} />
          <div>
            {Object.keys(LABEL).map((k) => {
              const v = risks ? risks[k] : null
              const b = base ? base[k] : null
              return (
                <div className="organ-row" key={k}>
                  <div style={{ width: 170 }}>{LABEL[k]}</div>
                  <div className="bar"><i style={{ width: `${Math.min(100, (v || 0) * 400)}%`, background: riskColor(v) }} /></div>
                  <div className="mono" style={{ width: 70, textAlign: 'right' }}>{v == null ? '…' : pct(v, 1)}</div>
                  <div className="mono muted" style={{ width: 90, textAlign: 'right' }}>{mode === 'change' && b != null && v != null ? <span className={v - b > 0 ? 'up' : 'down'}>{v - b >= 0 ? '+' : ''}{(100 * (v - b)).toFixed(2)} pp</span> : ''}</div>
                </div>
              )
            })}
            <div className="sub" style={{ marginTop: 10 }}>
              Cumulative-hazard accumulators looped over a representative week for 10 years; P = 1 − exp(−dmg). Coefficients (DCCT/UKPDS) in <code>backend/engine/params.yaml</code>.
              {baseline ? ` Baseline A1c-equivalent ${baseline.week_summary.baseline.a1c_equivalent.toFixed(2)} %.` : ''}
            </div>
            <h3 style={{ marginTop: 16 }}>Strain accumulated so far (13 weeks of data)</h3>
            <div className="kv">
              {Object.keys(LABEL).map((k) => <React.Fragment key={k}><span className="k">{LABEL[k]}</span><span className="mono">{strain ? strain[k].toFixed(4) : '…'}</span><span className="u">cum. hazard</span></React.Fragment>)}
            </div>
          </div>
        </div>
      </div>
      {pendingChange ? (
        <div className="card">
          <h3>Pending change: /change {pendingChange.change} → <span className={`badge ${pendingChange.verdict}`}>{pendingChange.verdict.replace(/_/g, ' ')}</span></h3>
          <div className="sub">{pendingChange.reason}</div>
        </div>
      ) : null}
    </div>
  )
}
