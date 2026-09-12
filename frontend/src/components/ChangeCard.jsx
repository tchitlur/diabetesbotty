import React from 'react'

// /change answer: recommendation, reason, and the 30-day comparison for the four things that matter.
export default function ChangeCard({ resp }) {
  const tone = resp.plain?.tone || 'off'
  const fmt = (r, v) => (r.key === 'lows' ? `${Math.round(v)}` : `${Math.round(v)}${r.unit === '%' ? '%' : ''}`)
  return (
    <div className={`answer ${tone}`}>
      <div className="headline">{resp.plain?.headline}</div>
      <div className="reason">{resp.plain?.reason}</div>
      <div className="compare">
        <span className="h">over the next 30 days</span><span className="h n">now</span><span className="h n">with the change</span><span className="h n"></span>
        {resp.summary_30d.map((r) => {
          const d = r.after - r.before
          const good = r.higher_is_better ? d > 0 : d < 0
          const cls = Math.abs(d) < 0.5 ? 'flat' : good ? 'down' : 'up'
          return (
            <React.Fragment key={r.key}>
              <span>{r.label} <span className="faint xs">{r.unit !== '%' ? r.unit : ''}</span></span>
              <span className="n">{fmt(r, r.before)}</span>
              <span className="n">{fmt(r, r.after)}</span>
              <span className={`delta ${cls}`}>{Math.abs(d) < 0.5 ? 'same' : `${d > 0 ? '+' : ''}${r.key === 'lows' ? Math.round(d) : Math.round(d)}${r.unit === '%' ? '%' : ''}`}</span>
            </React.Fragment>
          )
        })}
      </div>
      <div className="foot"><details style={{ width: '100%' }}><summary>details</summary><pre>{JSON.stringify({ change: resp.change, verdict: resp.verdict, reason: resp.reason, summary_30d: resp.summary_30d }, null, 2)}</pre></details></div>
    </div>
  )
}
