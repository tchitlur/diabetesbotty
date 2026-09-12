// Shared Recharts styling so every chart reads the same: tick style, tooltip style,
// axis-label helpers. Colours come from the CSS tokens.
export const TICK = { fontSize: 11, fill: '#9aa7b5' }
export const TIP = { background: '#0b0f14', border: '1px solid #2a3441', fontSize: 12, borderRadius: 6 }
export const GRID = { stroke: '#2a3441', strokeDasharray: '3 3' }
export const xLabel = (value) => ({ value, position: 'insideBottom', offset: -4, fill: '#9aa7b5', fontSize: 11 })
export const yLabel = (value, side = 'left') => ({ value, angle: -90, position: side === 'left' ? 'insideLeft' : 'insideRight', fill: '#9aa7b5', fontSize: 11, style: { textAnchor: 'middle' } })
export const MARGIN = { left: 8, right: 18, top: 8, bottom: 18 }
export const COLORS = { accent: '#4cc9f0', good: '#3fb950', warn: '#d29922', bad: '#f85149', s2: '#a371f7', s3: '#ff9f43', s4: '#8b98a8', cgm: '#e6edf3' }
export const legendFilter = (hidden = []) => (value, entry) => (hidden.includes(entry?.dataKey) ? null : value)
