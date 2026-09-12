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
    throw new Error(`${res.status}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`)
  }
  return res.json()
}

export const api = {
  health: () => req('/health'),
  // profiles (JSON files on the backend; nothing in the browser)
  profiles: () => req('/profiles'),
  activeProfile: () => req('/profiles/active'),
  createProfile: (body) => req('/profiles', { method: 'POST', body: JSON.stringify(body) }),
  selectProfile: (id) => req(`/profiles/${encodeURIComponent(id)}/select`, { method: 'POST' }),
  // screens
  home: () => req('/home'),
  timeline: (body) => req('/plan/timeline', { method: 'POST', body: JSON.stringify(body || {}) }),
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
  plan: (drinks = 0) => req(`/plan?date=tomorrow&drinks=${drinks}`),
  change: (name) => req('/change', { method: 'POST', body: JSON.stringify({ name }) }),
  alerts: () => req('/alerts'),
  replayDays: () => req('/replay/days'),
  replaySuggest: () => req('/replay/suggest'),
  replay: (body) => req('/replay', { method: 'POST', body: JSON.stringify(body) }),
  drift: () => req('/drift'),
  trends: () => req('/trends'),
  why: () => req('/why'),
  twinSummary: () => req('/twin/summary'),
  permissionCompare: (event) => req('/permission/compare', { method: 'POST', body: JSON.stringify({ event }) }),
  reset: () => req('/demo/reset', { method: 'POST' }),
}

// ------------------------------------------------------------ formatting rules
// times: 12-hour clock "7:30 pm" · dates: "Sat, Sep 12" · glucose: integer mg/dL · probabilities: whole percent
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
export const fmtTime = (iso) => {
  if (!iso || iso.length < 16) return ''
  const h24 = Number(iso.slice(11, 13)), m = iso.slice(14, 16)
  if (Number.isNaN(h24)) return ''
  return `${h24 % 12 || 12}:${m} ${h24 < 12 ? 'am' : 'pm'}`
}
export const fmtDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso.length === 10 ? iso + 'T00:00' : iso)
  return Number.isNaN(d.getTime()) ? iso : `${WD[d.getDay()]}, ${MON[d.getMonth()]} ${d.getDate()}`
}
export const fmtWhen = (iso) => (iso ? `${fmtDate(iso)} ${fmtTime(iso)}` : '')
// "today at 7:00 pm" / "tonight at 10:00 pm" / "tomorrow at 7:00 am", relative to the twin's clock
export const fmtRel = (iso, nowIso) => {
  if (!iso) return ''
  const d = new Date(iso), n = new Date(nowIso || iso)
  if (Number.isNaN(d.getTime())) return iso
  const days = Math.round((new Date(d.toDateString()) - new Date(n.toDateString())) / 86400000)
  const day = days === 0 ? (d.getHours() >= 17 ? 'tonight' : 'today') : days === 1 ? 'tomorrow' : d.toLocaleDateString(undefined, { weekday: 'long' })
  return `${day} at ${fmtTime(iso)}`
}
export const minutesBetween = (a, b) => (new Date(b) - new Date(a)) / 60000
// shift an ISO minute string by whole minutes without going through UTC
export const shiftIso = (iso, minutes) => {
  const d = new Date(iso)
  d.setMinutes(d.getMinutes() + minutes)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}
export const pct = (x, d = 0) => (x == null || Number.isNaN(x) ? '–' : `${(100 * x).toFixed(d)}%`)
export const mgdl = (x) => (x == null || Number.isNaN(x) ? '–' : `${Math.round(x)}`)
export const num = (x, d = 1) => (x == null || Number.isNaN(x) ? '–' : Number(x).toFixed(d))
export const likely = (p) => (p == null ? 'uncertain' : p < 0.05 ? 'unlikely' : p < 0.2 ? 'possible' : p < 0.5 ? 'likely' : 'very likely')

// plain phrase for an event: "2 beers", "a 30 min run"
export const eventPhrase = (e) => {
  if (!e) return 'that'
  if (e.label) return e.label
  if (e.type === 'exercise') return `a ${Math.round(e.duration_min || 30)} min workout`
  if (e.type === 'alcohol') { const n = Math.max(1, Math.round((e.alcohol_g || 14) / 14)); return `${n} drink${n > 1 ? 's' : ''}` }
  if (e.type === 'caffeine') return 'a coffee'
  if (e.type === 'meal') return `a meal with ${Math.round(e.carbs_g || 0)} g carbs`
  return e.type
}
