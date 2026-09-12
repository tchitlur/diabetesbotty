import React from 'react'

// Five organs drawn as simple SVG shapes; fill colour encodes 10-year risk.
export function riskColor(p) {
  // 0 -> green, 0.08 -> amber, 0.2+ -> red (piecewise interpolation in HSL)
  const x = Math.max(0, Math.min(1, (p || 0) / 0.2))
  const hue = 120 * (1 - x)
  return `hsl(${hue.toFixed(0)}, 70%, 45%)`
}

export default function OrganMap({ risks, title }) {
  const c = (k) => riskColor(risks?.[k])
  return (
    <svg viewBox="0 0 300 420" width="300" height="420" style={{ background: 'var(--panel-2)', borderRadius: 12 }}>
      <text x="150" y="22" textAnchor="middle" fill="var(--muted)" fontSize="12">{title}</text>
      {/* body silhouette */}
      <path d="M150 40 c-18 0 -30 14 -30 32 c0 14 8 24 18 29 c-40 8 -68 30 -70 70 l-6 100 l26 3 l6 -78 l4 190 l30 0 l10 -110 l10 110 l30 0 l4 -190 l6 78 l26 -3 l-6 -100 c-2 -40 -30 -62 -70 -70 c10 -5 18 -15 18 -29 c0 -18 -12 -32 -30 -32 z" fill="#0f1419" stroke="var(--border)" />
      {/* eyes */}
      <g>
        <ellipse cx="139" cy="66" rx="8" ry="5" fill={c('dmg_eye')} stroke="#0b0f14" />
        <ellipse cx="161" cy="66" rx="8" ry="5" fill={c('dmg_eye')} stroke="#0b0f14" />
        <circle cx="139" cy="66" r="2.2" fill="#0b0f14" /><circle cx="161" cy="66" r="2.2" fill="#0b0f14" />
        <text x="210" y="70" fill="var(--muted)" fontSize="11">eyes</text>
      </g>
      {/* heart */}
      <g>
        <path d="M160 150 c-6 -12 -24 -10 -24 4 c0 12 14 22 24 30 c10 -8 24 -18 24 -30 c0 -14 -18 -16 -24 -4 z" fill={c('dmg_cardio')} stroke="#0b0f14" />
        <text x="210" y="165" fill="var(--muted)" fontSize="11">heart</text>
      </g>
      {/* liver */}
      <g>
        <path d="M110 200 c-14 6 -20 20 -14 32 c6 12 24 16 44 12 c18 -4 30 -12 26 -24 c-4 -12 -26 -20 -56 -20 z" fill={c('dmg_liver')} stroke="#0b0f14" />
        <text x="60" y="222" fill="var(--muted)" fontSize="11">liver</text>
      </g>
      {/* kidneys */}
      <g>
        <path d="M128 262 c-10 0 -14 10 -12 22 c2 10 10 16 16 12 c4 -3 2 -8 2 -14 c0 -8 2 -20 -6 -20 z" fill={c('dmg_kidney')} stroke="#0b0f14" />
        <path d="M172 262 c10 0 14 10 12 22 c-2 10 -10 16 -16 12 c-4 -3 -2 -8 -2 -14 c0 -8 -2 -20 6 -20 z" fill={c('dmg_kidney')} stroke="#0b0f14" />
        <text x="210" y="285" fill="var(--muted)" fontSize="11">kidneys</text>
      </g>
      {/* nerves: branching lines down the legs and arms */}
      <g stroke={c('dmg_nerve')} strokeWidth="2.5" fill="none" strokeLinecap="round">
        <path d="M150 120 v60 M150 180 l-20 30 l-10 120 M150 180 l20 30 l10 120 M120 150 l-28 40 l-8 60 M180 150 l28 40 l8 60" />
        <path d="M135 330 l-8 20 M165 330 l8 20 M90 250 l-8 12 M210 250 l8 12" />
        <text x="60" y="360" fill="var(--muted)" fontSize="11" stroke="none">nerves</text>
      </g>
      <text x="150" y="410" textAnchor="middle" fill="var(--muted)" fontSize="10">green = low 10-year risk · red = high</text>
    </svg>
  )
}
