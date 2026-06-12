import { useState } from 'react'
import { api } from '../api'
import styles from './CreateJobForm.module.css'

const INTERVALS = ['', 'every_1_minute', 'every_5_minutes', 'every_1_hour']

export default function CreateJobForm({ onCreated }) {
  const [form, setForm] = useState({
    type: 'webhook',
    priority: 2,
    payload: '{\n  "url": "https://webhook.site/your-id",\n  "event": "payment_confirmed",\n  "data": { "order_id": "ORD-001" }\n}',
    scheduled_at: '',
    recurring_interval: '',
    dependency_ids: '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  function set(key, val) { setForm(f => ({ ...f, [key]: val })) }

  async function submit(e) {
    e.preventDefault()
    setError('')
    let payload
    try { payload = JSON.parse(form.payload) }
    catch { setError('Payload must be valid JSON'); return }

    const body = {
      type: form.type,
      priority: Number(form.priority),
      payload,
      scheduled_at: form.scheduled_at || null,
      recurring_interval: form.recurring_interval || null,
      dependency_ids: form.dependency_ids
        ? form.dependency_ids.split(',').map(s => s.trim()).filter(Boolean)
        : [],
    }
    setLoading(true)
    try {
      const res = await api.createJob(body)
      if (res.id) { onCreated(); setForm(f => ({ ...f, payload: '{\n  "url": "https://webhook.site/your-id",\n  "event": "payment_confirmed",\n  "data": {}\n}' })) }
      else setError(res.detail ?? 'Failed to create job')
    } finally { setLoading(false) }
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      <div className={styles.row}>
        <div className={styles.field}>
          <label>Job Type</label>
          <input value={form.type} onChange={e => set('type', e.target.value)} required />
        </div>
        <div className={styles.field}>
          <label>Priority</label>
          <select value={form.priority} onChange={e => set('priority', e.target.value)}>
            <option value={1}>1 — High</option>
            <option value={2}>2 — Medium</option>
            <option value={3}>3 — Low</option>
          </select>
        </div>
        <div className={styles.field}>
          <label>Recurring Interval</label>
          <select value={form.recurring_interval} onChange={e => set('recurring_interval', e.target.value)}>
            {INTERVALS.map(i => <option key={i} value={i}>{i || '— none —'}</option>)}
          </select>
        </div>
        <div className={styles.field}>
          <label>Scheduled At (UTC)</label>
          <input type="datetime-local" value={form.scheduled_at} onChange={e => set('scheduled_at', e.target.value ? `${e.target.value}:00Z` : '')} />
        </div>
      </div>
      <div className={styles.field}>
        <label>Dependency Job IDs <span className={styles.hint}>(comma-separated UUIDs)</span></label>
        <input placeholder="optional" value={form.dependency_ids} onChange={e => set('dependency_ids', e.target.value)} />
      </div>
      <div className={styles.field}>
        <label>Payload <span className={styles.hint}>(JSON)</span></label>
        <textarea rows={6} value={form.payload} onChange={e => set('payload', e.target.value)} />
      </div>
      {error && <div className={styles.error}>{error}</div>}
      <button className={styles.submit} type="submit" disabled={loading}>
        {loading ? 'Creating…' : 'Create Job'}
      </button>
    </form>
  )
}
