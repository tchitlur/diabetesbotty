import React from 'react'
import { pct, verdictTone } from '../api.js'

const ORGAN = { dmg_eye: 'eyes', dmg_kidney: 'kidneys', dmg_nerve: 'nerves', dmg_cardio: 'heart', dmg_liver: 'liver' }
const VERDICT = { merged: 'Merged into the plan', merged_with_changes: 'Merged with changes', rejected: 'Rejected' }
const KEY_ROWS = ['glucose', 'hba1c', 'sleep_debt', 'insulin_sensitivity', 'fat_mass', 'dmg_eye', 'dmg_kidney', 'dmg_nerve', 'dmg_cardio', 'dmg_liver']

function fmt(r, v) {
  if (r.variable === 'glucose') return Math.round(v).toString()
  if (Math.abs(r.baseline_10y) < 1 && Math.abs(r.baseline_30d) < 1) return v.toFixed(4)
  return v.toFixed(2)
}
function Delta({ r, a, b }) {
  const d = b - a
  if (Math.abs(d) < 1e-9) return <span className="flat">=</span>
  const s = r.variable === 'glucose' ? Math.round(d).toString() : Math.abs(d) < 0.01 ? d.toFixed(4) : d.toFixed(2)
  return <span className={d > 0 ? 'up' : 'down'}>{d > 0 ? '+' : ''}{s}</span>
}

// compact = chat panel (4 columns, key rows); full = Today card (all 22 variables, 8 columns)
export default function ChangeCard({ resp, compact = false }) {
  const rows = compact ? resp.diff.filter((r) => KEY_ROWS.includes(r.variable)) : resp.diff
  return (
    <div className={`pcard ${verdictTone(resp.verdict)}`}>
      <div className="verdict">{VERDICT[resp.verdict] || resp.verdict}</div>
      <div className="what"><b>/change {resp.change}</b> · representative week starting {resp.week_summary?.week_start}</div>
      <div className="cond">{resp.reason}</div>
      <div className="organs5">
        {Object.entries(resp.organ_risk_change).map(([k, v]) => (
          <div key={k} title="10-year probability with the change (baseline underneath)">{ORGAN[k] || k}<b>{pct(v, 1)}</b><span className="faint">{pct(resp.organ_risk_baseline[k], 1)} now</span></div>
        ))}
      </div>
      <div className="tablewrap">
        {compact ? (
          <table>
            <thead><tr><th>variable</th><th className="num">30 d</th><th className="num">Δ 30 d</th><th className="num">Δ 10 y</th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.variable}><td>{r.variable.replace('dmg_', 'risk ')} <span className="faint">{r.unit}</span></td><td className="num">{fmt(r, r.change_30d)}</td><td className="num"><Delta r={r} a={r.baseline_30d} b={r.change_30d} /></td><td className="num"><Delta r={r} a={r.baseline_10y} b={r.change_10y} /></td></tr>)}</tbody>
          </table>
        ) : (
          <table>
            <thead><tr><th>variable</th><th>unit</th><th className="num">30 d base</th><th className="num">30 d change</th><th className="num">Δ</th><th className="num">10 y base</th><th className="num">10 y change</th><th className="num">Δ</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.variable}>
                <td>{r.variable}</td><td className="faint">{r.unit}</td>
                <td className="num">{fmt(r, r.baseline_30d)}</td><td className="num">{fmt(r, r.change_30d)}</td><td className="num"><Delta r={r} a={r.baseline_30d} b={r.change_30d} /></td>
                <td className="num">{fmt(r, r.baseline_10y)}</td><td className="num">{fmt(r, r.change_10y)}</td><td className="num"><Delta r={r} a={r.baseline_10y} b={r.change_10y} /></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <div className="line">{compact ? 'Key rows; the Today tab has all 22 state variables. Body tab: toggle "pending change".' : 'Fast-layer rows are weekly means; medium rows at day 30 and year 10; risk rows are cumulative hazards.'}</div>
    </div>
  )
}
