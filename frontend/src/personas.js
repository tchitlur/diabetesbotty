// One-line descriptions of a person, built from the profile fields the backend stores.
export const sexWord = (s) => (s === 'F' ? 'female' : s === 'M' ? 'male' : 'other')

// "Software engineer · runs before work · T1D for 12 years · 90 days on a sensor"
export const describe = (p) => [
  p.occupation,
  p.habit,
  p.t1d_years ? `T1D for ${p.t1d_years} years` : null,
  p.sensor_days ? `${p.sensor_days} days on a sensor` : null,
].filter(Boolean).join(' · ')

// "34 · male · 96 kg · 1 u covers 37 g · target 70–180"
export const detailLine = (p) => [
  p.age, sexWord(p.sex), `${Math.round(p.weight_kg)} kg`, `1 u covers ${Math.round(p.carb_ratio_g_per_u)} g`, `target ${Math.round(p.target_low)}–${Math.round(p.target_high)}`,
].join(' · ')

// "34 · male · 96 kg · 180 cm · Software engineer" (the header pill)
export const headerLine = (p) => [p.age, sexWord(p.sex), `${Math.round(p.weight_kg)} kg`, `${Math.round(p.height_cm)} cm`, p.occupation].filter(Boolean).join(' · ')

// "carb ratio 1 u : 37 g · target 70–180" (the switcher rows)
export const ratioLine = (p) => `carb ratio 1 u : ${Math.round(p.carb_ratio_g_per_u)} g · target ${Math.round(p.target_low)}–${Math.round(p.target_high)}`

export const avatarOf = (p) => p.avatar || (p.name || '?')[0].toUpperCase()
