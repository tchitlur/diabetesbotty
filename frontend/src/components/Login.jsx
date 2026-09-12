import React, { useState } from 'react'
import { api } from '../api.js'
import { describe, detailLine, avatarOf } from '../personas.js'

const EMPTY = { name: '', age: 34, sex: 'F', weight_kg: 70, height_cm: 170, carb_ratio_g_per_u: 12, correction_factor_mgdl_per_u: 50, target_low: 70, target_high: 180 }

// First screen: the wordmark, "WHO IS THIS?" with one row per person, then Random / Add by hand.
export default function Login({ profiles, error, onEnter, onCreated, startAdding = false }) {
  const [adding, setAdding] = useState(startAdding)
  const [form, setForm] = useState(EMPTY)
  const [busy, setBusy] = useState(null)   // 'create' | 'random' | profile id
  const [err, setErr] = useState(null)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'number' ? Number(e.target.value) : e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    if (busy) return
    setBusy('create'); setErr(null)
    try { onCreated(await api.createProfile(form)) } catch (ex) { setErr(String(ex.message)) } finally { setBusy(null) }
  }
  const random = async () => {
    if (busy) return
    setBusy('random'); setErr(null)
    try { onCreated(await api.randomProfile()) } catch (ex) { setErr(String(ex.message)) } finally { setBusy(null) }
  }
  const enter = async (p) => {
    if (busy) return
    setBusy(p.id); setErr(null)
    try { await onEnter(p) } catch (ex) { setErr(String(ex.message)); setBusy(null) }
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
            <div className="persona-list" data-testid="login-list">
              {profiles.map((p) => (
                <button key={p.id} type="button" className="persona-row" onClick={() => enter(p)} disabled={!!busy} data-testid={`login-${p.id}`}>
                  <span className="avatar lg emoji">{avatarOf(p)}</span>
                  <span className="lines">
                    <b>{p.name}</b>
                    {describe(p) ? <small>{describe(p)}</small> : null}
                    <small>{detailLine(p)}</small>
                  </span>
                  {busy === p.id ? <span className="spinner" /> : null}
                </button>
              ))}
              {profiles.length === 0 && !error ? <div className="status"><span className="spinner" />Loading people…</div> : null}
            </div>
            <div className="actions two">
              <button type="button" className="primary" onClick={random} disabled={!!busy}>{busy === 'random' ? 'Making someone up and fitting their twin…' : '🎲 Random new person'}</button>
              <button type="button" onClick={() => setAdding(true)} disabled={!!busy}>Add someone by hand</button>
            </div>
            {err ? <div className="status error">{err}</div> : null}
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
              <button type="submit" className="primary" disabled={!!busy}>{busy === 'create' ? 'Setting up your twin (about 10 s)…' : 'Create profile'}</button>
              <button type="button" onClick={() => setAdding(false)} disabled={!!busy}>Back</button>
              {busy === 'create' ? <span className="status"><span className="spinner" />Matching you to a virtual person and fitting the model to their data</span> : null}
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
