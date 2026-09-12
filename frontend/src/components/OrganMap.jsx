import React from 'react'
import { riskTone, pct } from '../api.js'

const FILL = { good: '#3fb950', warn: '#d29922', bad: '#f85149', off: '#3a4553' }

// Five organs as simple SVG shapes. Fill = the same three verdict colours used everywhere
// (green < 5 %, amber 5–10 %, red > 10 % ten-year probability); each organ shows its percentage.
export default function OrganMap({ risks, title }) {
  const c = (k) => FILL[riskTone(risks?.[k])]
  const t = (k) => (risks?.[k] == null ? '–' : pct(risks[k], 1))
  const label = (x, y, k, name, anchor = 'start') => (
    <g>
      <text x={x} y={y} fill="#9aa7b5" fontSize="11" textAnchor={anchor}>{name}</text>
      <text x={x} y={y + 14} fill="#e6edf3" fontSize="13" fontWeight="700" textAnchor={anchor}>{t(k)}</text>
    </g>
  )
  return (
    <svg viewBox="0 0 320 430" width="320" height="430" style={{ background: '#1f2731', borderRadius: 10 }} role="img" aria-label="organ risk map">
      <text x="160" y="22" textAnchor="middle" fill="#9aa7b5" fontSize="12">{title}</text>
      <path d="M160 40 c-18 0 -30 14 -30 32 c0 14 8 24 18 29 c-40 8 -68 30 -70 70 l-6 100 l26 3 l6 -78 l4 190 l30 0 l10 -110 l10 110 l30 0 l4 -190 l6 78 l26 -3 l-6 -100 c-2 -40 -30 -62 -70 -70 c10 -5 18 -15 18 -29 c0 -18 -12 -32 -30 -32 z" fill="#0f1419" stroke="#2a3441" />
      <ellipse cx="149" cy="66" rx="8" ry="5" fill={c('dmg_eye')} stroke="#0b0f14" />
      <ellipse cx="171" cy="66" rx="8" ry="5" fill={c('dmg_eye')} stroke="#0b0f14" />
      <circle cx="149" cy="66" r="2.2" fill="#0b0f14" /><circle cx="171" cy="66" r="2.2" fill="#0b0f14" />
      {label(226, 62, 'dmg_eye', 'eyes')}
      <path d="M170 150 c-6 -12 -24 -10 -24 4 c0 12 14 22 24 30 c10 -8 24 -18 24 -30 c0 -14 -18 -16 -24 -4 z" fill={c('dmg_cardio')} stroke="#0b0f14" />
      {label(226, 158, 'dmg_cardio', 'heart')}
      <path d="M120 200 c-14 6 -20 20 -14 32 c6 12 24 16 44 12 c18 -4 30 -12 26 -24 c-4 -12 -26 -20 -56 -20 z" fill={c('dmg_liver')} stroke="#0b0f14" />
      {label(94, 214, 'dmg_liver', 'liver', 'end')}
      <path d="M138 262 c-10 0 -14 10 -12 22 c2 10 10 16 16 12 c4 -3 2 -8 2 -14 c0 -8 2 -20 -6 -20 z" fill={c('dmg_kidney')} stroke="#0b0f14" />
      <path d="M182 262 c10 0 14 10 12 22 c-2 10 -10 16 -16 12 c-4 -3 -2 -8 -2 -14 c0 -8 -2 -20 6 -20 z" fill={c('dmg_kidney')} stroke="#0b0f14" />
      {label(226, 278, 'dmg_kidney', 'kidneys')}
      <g stroke={c('dmg_nerve')} strokeWidth="2.5" fill="none" strokeLinecap="round">
        <path d="M160 120 v60 M160 180 l-20 30 l-10 120 M160 180 l20 30 l10 120 M130 150 l-28 40 l-8 60 M190 150 l28 40 l8 60" />
        <path d="M145 330 l-8 20 M175 330 l8 20 M100 250 l-8 12 M220 250 l8 12" />
      </g>
      {label(94, 350, 'dmg_nerve', 'nerves', 'end')}
      <text x="160" y="418" textAnchor="middle" fill="#9aa7b5" fontSize="10">10-year probability: green &lt; 5 % · amber 5–10 % · red &gt; 10 %</text>
    </svg>
  )
}
