import React from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { fmtTime, fmtWhen, fmtDate, pct } from '../api.js'
import Status, { ChartBox } from './Status.jsx'
import { TICK, TIP, GRID, xLabel, yLabel, MARGIN, COLORS } from './chart.js'
import PermissionCard from './PermissionCard.jsx'
import ChangeCard from './ChangeCard.jsx'

const TONE = { green: 'good', amber: 'warn', red: 'bad' }
const MARK = { meal: '🍽', insulin: '💉', exercise: '🏃', alcohol: '🍺', caffeine: '☕', sleep: '🌙' }

export default function TodayTab({ cards, planned, plan, alerts, onAccepted }) {
  const p = plan.data
  const energy = p ? p.energy_times.map((t, i) => ({ t: fmtTime(t), e: p.energy_curve[i] })) : []
  const evAt = (h) => (p ? p.placed_events.filter((e) => e.start_time.slice(0, 10) === p.date && Number(e.start_time.slice(11, 13)) === h) : [])
  return (
    <div className="grid">
      <div className="card">
        <h3>Tomorrow's plan {p ? `· ${fmtDate(p.date)}` : ''}</h3>
        <Status loading={plan.loading && !p} error={plan.error} loadingText="Grid-searching workout time, snack and drink cutoff (about 5 s)…">
          {p ? <>
            <div className="timeline">
              {p.timeline.map((b) => {
                const ev = evAt(Number(b.start.slice(11, 13)))
                return <div key={b.start} className={`tl-block ${TONE[b.color]}`} title={`${fmtTime(b.start)}–${fmtTime(b.end)}: ${b.label}${ev.length ? ` · ${ev.map((e) => e.label || e.type).join(', ')}` : ''}`}><span className="h">{b.start.slice(11, 13)}</span><span className="m">{ev.length ? MARK[ev[0].type] || '•' : ''}</span></div>
              })}
            </div>
            <div className="legend"><span><i className="good" />in range 70–180</span><span><i className="warn" />near a low (70–85) or above 180</span><span><i className="bad" />below 70 or above 250</span><span className="faint">hover a block for details; icons mark planned events</span></div>
            <div className="kv" style={{ marginTop: 'var(--s3)' }}>
              <span className="k">Workout</span><b className="v">{p.workout_start ? fmtWhen(p.workout_start) : 'none'}</b><span />
              <span className="k">Snack</span><b className="v">{p.snack_time ? fmtWhen(p.snack_time) : 'none needed'}</b><span />
              <span className="k">Drink cutoff</span><b className="v">{p.drink_cutoff ? fmtTime(p.drink_cutoff) : 'no drinks planned'}</b><span />
              <span className="k">P(hypo) around the workout</span><b className="v">{pct(p.p_hypo)}</b><span />
              <span className="k">Time in range, day</span><b className="v">{pct(p.tir)}</b><span />
            </div>
            <div className="note">{p.notes.join(' ')}</div>
            <ChartBox loading={plan.loading} height={130}>
              <ResponsiveContainer width="100%" height={130}>
                <LineChart data={energy} margin={MARGIN}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="t" tick={TICK} interval={5} label={xLabel('time (HH:MM)')} />
                  <YAxis domain={[0, 100]} tick={TICK} width={40} label={yLabel('energy')} />
                  <Tooltip contentStyle={TIP} formatter={(v) => [Math.round(v), 'energy score']} />
                  <Line type="monotone" dataKey="e" stroke={COLORS.good} dot={false} name="energy score (0–100)" isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartBox>
          </> : null}
        </Status>
      </div>

      <div className="grid two">
        <div className="card">
          <h3>Pending alerts (doing nothing)</h3>
          <Status loading={alerts.loading && !alerts.data} error={alerts.error} empty={alerts.data && alerts.data.length === 0} emptyText="No crossing of 70 or 250 mg/dL with probability ≥ 15 % in the next 8 h." loadingText="Checking the do-nothing forecast…">
            {alerts.data?.map((a, i) => <div key={i} className={`alert ${a.kind}`}><b>{a.kind}</b>{a.message}</div>)}
          </Status>
        </div>
        <div className="card">
          <h3>Committed to the plan</h3>
          <Status empty={planned.length === 0} emptyText='Nothing yet. Approve a card in the chat and press "Add to plan"; the forecast and the plan update.'>
            <table><thead><tr><th>when</th><th>event</th><th className="num">amount</th></tr></thead><tbody>
              {planned.map((e, i) => <tr key={i}><td>{fmtWhen(e.start_time)}</td><td>{e.label || e.type}</td><td className="num">{e.carbs_g ? `${Math.round(e.carbs_g)} g carbs ` : ''}{e.alcohol_g ? `${Math.round(e.alcohol_g)} g alcohol ` : ''}{e.caffeine_mg ? `${Math.round(e.caffeine_mg)} mg ` : ''}{e.type === 'exercise' ? `${Math.round(e.duration_min)} min` : ''}</td></tr>)}
            </tbody></table>
          </Status>
        </div>
      </div>

      <div className="card">
        <h3>Cards from this session</h3>
        <Status empty={cards.length === 0} emptyText='Ask the chat ("can I have two more beers tonight?") and every card lands here too.'>
          <div className="grid">
            {cards.map((c) => c.kind === 'change' ? <ChangeCard key={c.at} resp={c.payload} /> : <PermissionCard key={c.at} card={c.payload} compact onAccepted={onAccepted} />)}
          </div>
        </Status>
      </div>
    </div>
  )
}
