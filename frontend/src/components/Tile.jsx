import React from 'react'

// One tile, one layout for every tile: icon + label (never wraps), one large value with unit,
// one fill bar, one status word. The whole tile is a button; the chevron hints it opens.
export default function Tile({ tile, open, onClick }) {
  const t = tile
  return (
    <button type="button" className={`tile ${open ? 'open' : ''}`} onClick={onClick} aria-expanded={!!open} aria-label={`${t.label}: ${t.status}`}>
      <div className="t-row t-head"><span className="icon">{t.icon}</span><span className="label">{t.label}</span><span className="chev">{open ? '▾' : '▸'}</span></div>
      <div className="t-row t-val">{t.value}<span className="unit">{t.unit}</span></div>
      <div className="t-row t-bar"><i className={`fill-${t.tone}`} style={{ width: `${Math.round(100 * t.level)}%` }} /></div>
      <div className={`t-row t-word tone-${t.tone}`}>{t.status}</div>
    </button>
  )
}
