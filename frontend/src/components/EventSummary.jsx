import React from 'react'
import { fmtWhen } from '../api.js'

const FIELDS = [
  ['carbs_g', 'carbs', 'g'], ['fat_g', 'fat', 'g'], ['protein_g', 'protein', 'g'], ['fiber_g', 'fibre', 'g'],
  ['alcohol_g', 'alcohol', 'g'], ['caffeine_mg', 'caffeine', 'mg'], ['insulin_units', 'insulin', 'U'], ['water_ml', 'water', 'ml'],
  ['duration_min', 'duration', 'min'], ['intensity', 'intensity', '0–1'], ['sleep_hours', 'sleep', 'h'], ['severity', 'severity', '0–1'],
]

// The parsed event, readable: only the fields that carry a value, with units, plus the raw JSON collapsed.
export default function EventSummary({ event }) {
  const rows = [['type', event.type + (event.exercise_kind ? ` (${event.exercise_kind})` : '') + (event.insulin_kind ? ` (${event.insulin_kind})` : ''), '']]
  rows.push(['when', fmtWhen(event.start_time), ''])
  for (const [k, l, u] of FIELDS) {
    const v = event[k]
    if (v) rows.push([l, Number.isInteger(v) ? String(v) : Number(v).toFixed(1).replace(/\.0$/, ''), u])
  }
  rows.push(['uncertainty', `±${Math.round(100 * (event.uncertainty || 0))}%`, 'of the amounts'])
  return (
    <div>
      <div className="evgrid">
        {rows.map(([k, v, u]) => <React.Fragment key={k}><span className="k">{k}</span><span className="v">{v}{u ? <span className="faint"> {u}</span> : null}</span></React.Fragment>)}
      </div>
      <details><summary>raw event JSON (the exact contract the simulator receives)</summary><pre>{JSON.stringify(event, null, 2)}</pre></details>
    </div>
  )
}
