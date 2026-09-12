import React, { useEffect, useRef } from 'react'

export const EXAMPLES = ['Can I have pizza for dinner?', 'Is dessert okay right now?', 'Large coffee now', 'Run at 7 tomorrow?']
export const CHANGES = [
  ['morning_workouts', 'Move workouts to morning'],
  ['cut_caffeine', 'Cut caffeine'],
  ['drink_fridays_only', 'Weekend drinks only'],
  ['fasting_16_8', 'Skip breakfast, eat 12–8'],
]

// The "?" popover next to the chat input: examples to tap and the commands with plain labels.
export default function HelpPopover({ onPick, onClose }) {
  const ref = useRef(null)
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose() }
    const k = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('mousedown', h); document.addEventListener('keydown', k)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k) }
  }, [onClose])
  return (
    <div className="help" ref={ref} role="dialog" aria-label="help">
      <div className="help-title">Try asking</div>
      <div className="help-list">{EXAMPLES.map((x) => <button key={x} type="button" className="small" onClick={() => onPick(x)}>{x}</button>)}</div>
      <div className="help-title">What if I changed…</div>
      <div className="help-list">{CHANGES.map(([name, label]) => <button key={name} type="button" className="small" onClick={() => onPick(`/change ${name}`)}>{label}</button>)}</div>
      <div className="help-title">More</div>
      <div className="help-list">
        <button type="button" className="small" onClick={() => onPick('/plan tomorrow')}>Plan tomorrow's workout</button>
        <button type="button" className="small" onClick={() => onPick('/why')}>Why the last answer?</button>
      </div>
      <div className="faint xs">You can also log food, drinks and workouts with the buttons above.</div>
    </div>
  )
}
