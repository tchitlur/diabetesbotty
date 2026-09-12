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

export const fmtTime = (iso) => (iso ? iso.slice(11, 16) : '')
export const fmtDay = (iso) => (iso ? iso.slice(0, 10) : '')
export const pct = (x, d = 0) => `${(100 * (x || 0)).toFixed(d)}%`
