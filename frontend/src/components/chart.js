// Shared Recharts styling so every chart reads the same. Colours mirror the CSS tokens.
export const TICK = { fontSize: 12, fill: '#5f6a70' }
export const TIP = { background: '#ffffff', border: '1px solid #e3e5df', fontSize: 12, borderRadius: 8, color: '#24282b' }
export const GRID = { stroke: '#e3e5df', strokeDasharray: '3 3' }
export const xLabel = (value) => ({ value, position: 'insideBottom', offset: -4, fill: '#5f6a70', fontSize: 12 })
export const yLabel = (value, side = 'left') => ({ value, angle: -90, position: side === 'left' ? 'insideLeft' : 'insideRight', fill: '#5f6a70', fontSize: 12, style: { textAnchor: 'middle' } })
export const MARGIN = { left: 8, right: 18, top: 8, bottom: 18 }
export const COLORS = { accent: '#2f8f83', accentSoft: '#2f8f83', good: '#2f9e5f', warn: '#d68b1c', bad: '#d1443f', s2: '#7a6fb3', s3: '#c9782c', s4: '#8a949a', cgm: '#24282b', range: '#2f9e5f' }
export const legendFilter = (hidden = []) => (value, entry) => (hidden.includes(entry?.dataKey) ? null : value)
