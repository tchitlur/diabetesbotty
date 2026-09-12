import React, { useState } from 'react'

// Tap inputs build a proposed Event directly (source: "tap") so the engine can be
// demoed without typing. Amounts mirror the food table: 14 g alcohol per drink.
const DRINKS = { beer: { alcohol_g: 14, carbs_g: 13 }, wine: { alcohol_g: 14, carbs_g: 4 }, spirit: { alcohol_g: 14, carbs_g: 0 } }

export default function TapBar({ onTap, disabled }) {
  const [count, setCount] = useState(2)
  const now = () => new Date()  // the backend ignores the wall clock for "now"; we send an ISO string it maps to its own clock
  const drink = (kind) => {
    const d = DRINKS[kind]
    onTap({ type: 'alcohol', start_time: 'now', duration_min: Math.min(30 + 30 * count, 240), alcohol_g: d.alcohol_g * count, carbs_g: d.carbs_g * count,
            uncertainty: 0.2, source: 'tap', label: `${count} ${kind}${count > 1 ? 's' : ''}` })
  }
  return (
    <div className="taps">
      <span className="count"><button type="button" onClick={() => setCount((c) => Math.max(1, c - 1))} disabled={disabled}>−</button><b style={{ padding: '0 4px' }}>×{count}</b><button type="button" onClick={() => setCount((c) => Math.min(8, c + 1))} disabled={disabled}>+</button></span>
      <button type="button" onClick={() => drink('beer')} disabled={disabled}>🍺 beer</button>
      <button type="button" onClick={() => drink('wine')} disabled={disabled}>🍷 wine</button>
      <button type="button" onClick={() => drink('spirit')} disabled={disabled}>🥃 spirit</button>
      <button type="button" onClick={() => onTap({ type: 'caffeine', start_time: 'now', caffeine_mg: 95, uncertainty: 0.15, source: 'tap', label: 'coffee' })} disabled={disabled}>☕ coffee</button>
      <button type="button" onClick={() => onTap({ type: 'exercise', start_time: 'now', duration_min: 30, exercise_kind: 'aerobic', intensity: 0.6, uncertainty: 0.15, source: 'tap', label: 'run 30 min' })} disabled={disabled}>🏃 run 30 min</button>
      <button type="button" onClick={() => onTap({ type: 'exercise', start_time: 'now', duration_min: 45, exercise_kind: 'anaerobic', intensity: 0.7, uncertainty: 0.15, source: 'tap', label: 'lift 45 min' })} disabled={disabled}>🏋️ lift 45 min</button>
    </div>
  )
}
