// Thin fetch layer. Everything goes through the Vite proxy (/api -> 127.0.0.1:8000),
// so no host is hard-coded in React. No modeling logic lives here.
const BASE = '/api'

async function req(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: opts.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch (e) { /* ignore */ }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json()
}

export const api = {
  health: () => req('/health'),
  state: (stale) => req(`/state${stale != null ? `?stale=${stale}` : ''}`),
  forecast: (h = 480) => req(`/forecast?horizon_min=${h}`),
  history: (hours = 12) => req(`/history?hours=${hours}`),
  parse: (text) => req('/parse', { method: 'POST', body: JSON.stringify({ text }) }),
  parseImage: (file, hint = '') => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('hint', hint)
    return req('/parse/image', { method: 'POST', body: fd })
  },
  parserStatus: () => req('/parser/status'),
  permission: (event, stale) => req(`/permission${stale != null ? `?stale=${stale}` : ''}`, { method: 'POST', body: JSON.stringify({ event }) }),
  accept: (events) => req('/events/accept', { method: 'POST', body: JSON.stringify({ events }) }),
  planned: () => req('/events/planned'),
  recent: (hours = 24) => req(`/events/recent?hours=${hours}`),
  plan: (drinks = 0) => req(`/plan?date=tomorrow&drinks=${drinks}`),
  change: (name) => req('/change', { method: 'POST', body: JSON.stringify({ name }) }),
  changeOptions: () => req('/change/options'),
  budget: () => req('/budget'),
  alerts: () => req('/alerts'),
  replayDays: () => req('/replay/days'),
  replaySuggest: () => req('/replay/suggest'),
  replay: (body) => req('/replay', { method: 'POST', body: JSON.stringify(body) }),
  drift: () => req('/drift'),
  clinician: () => req('/clinician'),
  trends: () => req('/trends'),
  why: () => req('/why'),
  cards: () => req('/cards'),
  escalations: () => req('/escalations'),
  reset: () => req('/demo/reset', { method: 'POST' }),
}

// ------------------------------------------------------------ formatting rules
// glucose: integer mg/dL · probabilities: whole percent · times: HH:MM · dates: weekday + date
export const fmtTime = (iso) => (iso ? iso.slice(11, 16) : '')
export const fmtDay = (iso) => (iso ? iso.slice(0, 10) : '')
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
export const fmtWhen = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${WD[d.getDay()]} ${iso.slice(5, 10)} ${iso.slice(11, 16)}`
}
export const fmtDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso.length === 10 ? iso + 'T00:00' : iso)
  return Number.isNaN(d.getTime()) ? iso : `${WD[d.getDay()]} ${iso.slice(0, 10)}`
}
export const pct = (x, d = 0) => (x == null || Number.isNaN(x) ? '–' : `${(100 * x).toFixed(d)}%`)
export const mgdl = (x) => (x == null || Number.isNaN(x) ? '–' : `${Math.round(x)}`)
export const num = (x, d = 1) => (x == null || Number.isNaN(x) ? '–' : Number(x).toFixed(d))
export const verdictTone = (v) => ({ approved: 'good', merged: 'good', approved_with_condition: 'warn', merged_with_changes: 'warn', denied: 'bad', rejected: 'bad', escalate: 'bad', request_data: 'off' }[v] || 'off')
export const riskTone = (p) => (p == null ? 'off' : p < 0.05 ? 'good' : p < 0.10 ? 'warn' : 'bad')
export const RISK_THRESHOLDS = 'green < 5 % · amber 5–10 % · red > 10 % (10-year probability)'
