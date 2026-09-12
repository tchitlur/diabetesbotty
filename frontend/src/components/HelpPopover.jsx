import React, { useEffect, useRef } from 'react'

export const GROUPS = [
  ['Ask', ["What's my glucose?", "Why isn't my sugar rising after lunch?", 'How many lows did I have this week?']],
  ['Decide', ['Can I have pizza for dinner?', 'Run at 7 tomorrow?']],
  ['Log', ['I just had a large coffee', 'Ate a bagel 15 min ago']],
  ['Explore', ['What if I skip dinner?', '/plan tomorrow', '/change morning_workouts']],
]
export const EXAMPLES = GROUPS.flatMap(([, xs]) => xs)
export const CHANGES = [
  ['morning_workouts', 'Move workouts to morning'],
  ['cut_caffeine', 'Cut caffeine'],
  ['drink_fridays_only', 'Weekend drinks only'],
  ['fasting_16_8', 'Skip breakfast, eat 12–8'],
]

// The "?" popover next to the chat input: grouped examples to tap, and the /change options with plain labels.
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
      {GROUPS.map(([title, xs]) => (
        <React.Fragment key={title}>
          <div className="help-title">{title}</div>
          <div className="help-list">{xs.map((x) => <button key={x} type="button" className="small" onClick={() => onPick(x)}>{x}</button>)}</div>
        </React.Fragment>
      ))}
      <div className="help-title">What if I changed…</div>
      <div className="help-list">{CHANGES.map(([name, label]) => <button key={name} type="button" className="small" onClick={() => onPick(`/change ${name}`)}>{label}</button>)}</div>
      <div className="faint xs">Every answer comes from your model; the chips under it show which parts were checked.</div>
    </div>
  )
}
