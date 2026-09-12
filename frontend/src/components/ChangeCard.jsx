import React from 'react'
import { pct } from '../api.js'

export default function ChangeCard({ resp, compact = false }) {
  const rows = compact ? resp.diff.filter((r) => ['glucose', 'hba1c', 'sleep_debt', 'insulin_sensitivity', 'fat_mass', 'dmg_eye', 'dmg_cardio', 'dmg_liver'].includes(r.variable)) : resp.diff
  const d = (a, b, digits) => {
    const delta = b - a
    if (Math.abs(delta) < 1e-9) return <span className="muted">=</span>
    return <span className={delta > 0 ? 'up' : 'down'}>{delta > 0 ? '+' : ''}{delta.toFixed(digits)}</span>
  }
  const digits = (r) => (Math.abs(r.baseline_10y) < 1 ? 4 : 2)
  return (
    <div className="pcard">
      <div className="row"><span className={`badge ${resp.verdict}`}>{resp.verdict.replace(/_/g, ' ')}</span><b>/change {resp.change}</b></div>
      <div className="cond">{resp.reason}</div>
      <div className="stats" style={{ gridTemplateColumns: 'repeat(5, 1fr)' }}>
        {Object.entries(resp.organ_risk_change).map(([k, v]) => (
          <div key={k}><span className="muted">{k.replace('dmg_', '')} 10 y</span><b>{pct(v, 1)}</b><span className="muted">{pct(resp.organ_risk_baseline[k], 1)} now</span></div>
        ))}
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table>
          <thead><tr><th>variable</th><th>unit</th><th className="num">30 d base</th><th className="num">30 d change</th><th className="num">Δ</th><th className="num">10 y base</th><th className="num">10 y change</th><th className="num">Δ</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.variable}>
                <td>{r.variable}</td><td className="muted">{r.unit}</td>
                <td className="num">{r.baseline_30d.toFixed(digits(r))}</td><td className="num">{r.change_30d.toFixed(digits(r))}</td><td className="num">{d(r.baseline_30d, r.change_30d, digits(r))}</td>
                <td className="num">{r.baseline_10y.toFixed(digits(r))}</td><td className="num">{r.change_10y.toFixed(digits(r))}</td><td className="num">{d(r.baseline_10y, r.change_10y, digits(r))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {compact ? <div className="sub">Showing key rows; the chat card has all 22 state variables. Body tab: toggle "pending change".</div> : null}
    </div>
  )
}
