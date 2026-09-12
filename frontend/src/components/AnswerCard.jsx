import React, { useState } from 'react'
import { api, fmtTime } from '../api.js'
import Strip from './Strip.jsx'

// Every chat answer is this card, in this order: (a) the recommendation, one line, coloured by
// verdict; (b) the reason in plain sentences; (c) a 6-hour strip with the predicted band and a
// marker for the proposed action. Details (the engine's numbers) stay behind a link.
export default function AnswerCard({ plain, strip, card, onAccepted, onWhy, details, footer }) {
  const [added, setAdded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [pop, setPop] = useState(null)       // null | 'loading' | card (population parameters)
  const [showPop, setShowPop] = useState(false)
  const tone = plain?.tone || 'off'
  const compare = async () => {
    const next = !showPop
    setShowPop(next)
    if (next && !pop && card?.proposed) {
      setPop('loading')
      try { setPop(await api.permissionCompare(card.proposed)) } catch (e) { setPop({ error: String(e.message) }) }
    }
  }
  const canAdd = card && (card.verdict === 'approved' || card.verdict === 'approved_with_condition') && card.plan_events?.length
  const add = async () => {
    setBusy(true); setErr(null)
    try { await api.accept(card.plan_events); setAdded(true); onAccepted && onAccepted() } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div className={`answer ${tone}`}>
      <div className="headline">{plain?.headline}</div>
      <div className="reason">{plain?.reason}</div>
      {strip ? <div><div className="strip-title">{strip.title || 'Next 6 hours'}</div><Strip {...strip} /></div> : null}
      <div className="foot">
        {canAdd ? <button className="small primary" disabled={busy || added} onClick={add}>{added ? 'Added to your plan' : card.plan_events.length > 1 ? 'Add to plan (with the snack)' : 'Add to plan'}</button> : null}
        {onWhy ? <button className="small ghost" onClick={onWhy}>why?</button> : null}
        {card?.proposed && card.mini_curve ? <label className="toggle"><input type="checkbox" checked={showPop} onChange={compare} /> Compared to average</label> : null}
        {footer}
        {err ? <span className="err">{err}</span> : null}
        {details ? <details style={{ width: '100%' }}><summary>details</summary>{details}</details> : null}
      </div>
      {showPop ? (
        <div className={`compare-box ${pop && pop.plain ? pop.plain.tone : 'off'}`} data-testid="compare-box">
          <div className="xs muted">If the app did not know you (average person with T1D):</div>
          {pop === 'loading' || !pop ? <div className="status"><span className="spinner" />Re-running with average settings…</div> : pop.error ? <div className="err">{pop.error}</div> : <>
            <div className="headline small">{pop.plain.headline}{pop.verdict === card.verdict ? <span className="faint xs"> · same answer, different numbers</span> : <span className="faint xs"> · a different answer</span>}</div>
            <div className="reason">{pop.plain.reason}</div>
            {pop.mini_curve ? <Strip times={pop.mini_curve.times} line={pop.mini_curve.best_variant} p10={pop.mini_curve.p10} p90={pop.mini_curve.p90} markerIso={pop.proposed?.start_time} markerLabel="average" hours={6} height={100} nowLabel={fmtTime(card.proposed.start_time)} /> : null}
          </>}
        </div>
      ) : null}
    </div>
  )
}
