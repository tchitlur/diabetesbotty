import React, { useRef, useState } from 'react'

// The quick-log options, food first: Meal, Snack, Coffee, Drink, Workout.
// Used by the chat panel and by the header's "Log something" button. Emits either
// { text } (to be parsed) or { event } (built here, amounts from the food table) or { file }.
const DRINKS = { beer: { alcohol_g: 14, carbs_g: 13 }, wine: { alcohol_g: 14, carbs_g: 4 }, spirit: { alcohol_g: 14, carbs_g: 0 } }

export default function QuickLog({ onAction, disabled, parser }) {
  const [sub, setSub] = useState(null)   // 'meal' | 'drink' | 'workout'
  const [meal, setMeal] = useState('')
  const [carbs, setCarbs] = useState('')
  const [count, setCount] = useState(2)
  const fileRef = useRef(null)
  const photoOk = !!parser?.gemini_configured
  const now = 'now'
  const go = (a) => { setSub(null); setMeal(''); setCarbs(''); onAction(a) }

  const submitMeal = (e) => {
    e.preventDefault()
    if (meal.trim()) return go({ text: meal.trim() })
    const g = Number(carbs)
    if (g > 0) return go({ event: { type: 'meal', start_time: now, duration_min: 15, carbs_g: g, uncertainty: 0.3, source: 'tap', label: `meal, ${g} g carbs` } })
  }
  const drink = (kind) => {
    const d = DRINKS[kind]
    go({ event: { type: 'alcohol', start_time: now, duration_min: Math.min(30 + 30 * count, 240), alcohol_g: d.alcohol_g * count, carbs_g: d.carbs_g * count, uncertainty: 0.2, source: 'tap', label: `${count} ${kind}${count > 1 ? 's' : ''}` } })
  }
  return (
    <div className="quick">
      <button type="button" className={sub === 'meal' ? 'active' : ''} onClick={() => setSub(sub === 'meal' ? null : 'meal')} disabled={disabled}>🍽 Meal</button>
      <button type="button" onClick={() => go({ event: { type: 'meal', start_time: now, duration_min: 5, carbs_g: 15, uncertainty: 0.2, source: 'tap', label: 'small snack' } })} disabled={disabled}>🍎 Snack</button>
      <button type="button" onClick={() => go({ event: { type: 'caffeine', start_time: now, caffeine_mg: 95, uncertainty: 0.15, source: 'tap', label: 'coffee' } })} disabled={disabled}>☕ Coffee</button>
      <button type="button" className={sub === 'drink' ? 'active' : ''} onClick={() => setSub(sub === 'drink' ? null : 'drink')} disabled={disabled}>🍷 Drink</button>
      <button type="button" className={sub === 'workout' ? 'active' : ''} onClick={() => setSub(sub === 'workout' ? null : 'workout')} disabled={disabled}>🏃 Workout</button>

      {sub === 'meal' ? (
        <form className="sub" onSubmit={submitMeal}>
          <input type="text" value={meal} onChange={(e) => setMeal(e.target.value)} placeholder="what did you eat? e.g. pasta with chicken" aria-label="meal description" autoFocus />
          <span className="muted">or carbs</span>
          <input type="number" value={carbs} onChange={(e) => setCarbs(e.target.value)} placeholder="g" min={1} max={300} aria-label="carbs in grams" />
          <button type="submit" className="small primary" disabled={!meal.trim() && !(Number(carbs) > 0)}>Log meal</button>
          <input ref={fileRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) go({ file: f }) }} />
          <button type="button" className="small" onClick={() => fileRef.current?.click()} disabled={!photoOk} title={photoOk ? 'Photo of the plate: the amounts are estimated from the picture' : 'Photo needs the Gemini key (scripts\\setup_key.ps1)'}>📷 Photo</button>
        </form>
      ) : null}
      {sub === 'drink' ? (
        <div className="sub">
          <span>How many?</span>
          <button type="button" className="small" onClick={() => setCount((c) => Math.max(1, c - 1))}>−</button><b>{count}</b><button type="button" className="small" onClick={() => setCount((c) => Math.min(8, c + 1))}>+</button>
          <button type="button" className="small" onClick={() => drink('beer')}>🍺 Beer</button>
          <button type="button" className="small" onClick={() => drink('wine')}>🍷 Wine</button>
          <button type="button" className="small" onClick={() => drink('spirit')}>🥃 Spirit</button>
        </div>
      ) : null}
      {sub === 'workout' ? (
        <div className="sub">
          <button type="button" className="small" onClick={() => go({ event: { type: 'exercise', start_time: now, duration_min: 30, exercise_kind: 'aerobic', intensity: 0.6, uncertainty: 0.15, source: 'tap', label: 'run 30 min' } })}>🏃 Run 30 min</button>
          <button type="button" className="small" onClick={() => go({ event: { type: 'exercise', start_time: now, duration_min: 30, exercise_kind: 'aerobic', intensity: 0.4, uncertainty: 0.15, source: 'tap', label: 'walk 30 min' } })}>🚶 Walk 30 min</button>
          <button type="button" className="small" onClick={() => go({ event: { type: 'exercise', start_time: now, duration_min: 45, exercise_kind: 'anaerobic', intensity: 0.7, uncertainty: 0.15, source: 'tap', label: 'lift 45 min' } })}>🏋️ Lift 45 min</button>
        </div>
      ) : null}
    </div>
  )
}
