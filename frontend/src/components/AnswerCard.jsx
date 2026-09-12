import React, { useState } from 'react'
import { api } from '../api.js'
import Strip from './Strip.jsx'

// Every chat answer is this card, in this order: (a) the recommendation, one line, coloured by
// verdict; (b) the reason in plain sentences; (c) a 6-hour strip with the predicted band and a
// marker for the proposed action. Details (the engine's numbers) stay behind a link.
export default function AnswerCard({ plain, strip, card, onAccepted, onWhy, details, footer }) {
  const [added, setAdded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const tone = plain?.tone || 'off'
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
        {footer}
        {err ? <span className="err">{err}</span> : null}
        {details ? <details style={{ width: '100%' }}><summary>details</summary>{details}</details> : null}
      </div>
    </div>
  )
}
