import React, { useState } from 'react'
import { api } from '../api.js'

const EMPTY = { name: '', age: 34, sex: 'F', weight_kg: 70, height_cm: 170, carb_ratio_g_per_u: 12, correction_factor_mgdl_per_u: 50, target_low: 70, target_high: 180 }

// First screen: tap a profile, or add one. Profiles live on the backend as JSON files.
export default function Login({ profiles, error, onEnter, onCreated }) {
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'number' ? Number(e.target.value) : e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    if (busy) return
    setBusy(true); setErr(null)
    try {
      const p = await api.createProfile(form)
      onCreated(p)
    } catch (ex) { setErr(String(ex.message)) } finally { setBusy(false) }
  }

  return (
    <div className="login">
      <div className="box">
        <div>
          <div className="brand">Gluco<span>Pilot</span></div>
          <div className="tagline">What you eat and drink, and how your body handles it.</div>
        </div>
        {error ? <div className="status error">Backend not reachable ({error}). Start it with <code>.\run_demo.ps1</code>.</div> : null}
        {!adding ? (
          <div className="card">
            <h3>Who is this?</h3>
            <div className="profiles">
              {profiles.map((p) => (
                <button key={p.id} className="profile-btn" onClick={() => onEnter(p)}>
                  <span className="avatar lg">{p.initial}</span>
                  <span>{p.name}<small>{p.age} · {p.sex === 'F' ? 'female' : p.sex === 'M' ? 'male' : 'other'} · {Math.round(p.weight_kg)} kg · target {Math.round(p.target_low)}–{Math.round(p.target_high)} mg/dL</small></span>
                </button>
              ))}
              {profiles.length === 0 && !error ? <div className="status"><span className="spinner" />Loading profiles…</div> : null}
            </div>
            <div className="actions"><button className="primary" onClick={() => setAdding(true)}>Add profile</button></div>
            <div className="note">This is a demo: no passwords. Each profile is matched to a virtual person with 90 days of sensor data, and a model of that person is fitted when you add one.</div>
          </div>
        ) : (
          <form className="card" onSubmit={submit}>
            <h3>New profile</h3>
            <div className="form-grid">
              <label className="field wide">Name<input type="text" value={form.name} onChange={set('name')} required maxLength={40} autoFocus /></label>
              <label className="field">Age<input type="number" value={form.age} onChange={set('age')} min={10} max={100} required /></label>
              <label className="field">Sex<select value={form.sex} onChange={set('sex')}><option value="F">Female</option><option value="M">Male</option><option value="other">Other</option></select></label>
              <label className="field">Weight (kg)<input type="number" value={form.weight_kg} onChange={set('weight_kg')} min={30} max={240} step="0.5" required /></label>
              <label className="field">Height (cm)<input type="number" value={form.height_cm} onChange={set('height_cm')} min={110} max={225} required /></label>
              <label className="field">Carb ratio (g of carbs per unit of insulin)<input type="number" value={form.carb_ratio_g_per_u} onChange={set('carb_ratio_g_per_u')} min={3} max={59} step="0.5" required /></label>
              <label className="field">Correction factor (mg/dL lowered per unit)<input type="number" value={form.correction_factor_mgdl_per_u} onChange={set('correction_factor_mgdl_per_u')} min={6} max={199} required /></label>
              <label className="field">Target range, low (mg/dL)<input type="number" value={form.target_low} onChange={set('target_low')} min={60} max={120} required /></label>
              <label className="field">Target range, high (mg/dL)<input type="number" value={form.target_high} onChange={set('target_high')} min={120} max={250} required /></label>
            </div>
            {err ? <div className="status error">{err}</div> : null}
            <div className="actions">
              <button type="submit" className="primary" disabled={busy}>{busy ? 'Setting up your twin (about 10 s)…' : 'Create profile'}</button>
              <button type="button" onClick={() => setAdding(false)} disabled={busy}>Back</button>
              {busy ? <span className="status"><span className="spinner" />Matching you to a virtual person and fitting the model to their data</span> : null}
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
