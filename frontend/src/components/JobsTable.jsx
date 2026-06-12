import { useState } from 'react'
import { api } from '../api'
import styles from './JobsTable.module.css'

const STATUS_COLOR = { pending: 'yellow', processing: 'blue', completed: 'green', failed: 'red', cancelled: 'muted' }
const PRIORITY_LABEL = { 1: 'High', 2: 'Medium', 3: 'Low' }

function fmt(dt) {
  if (!dt) return '—'
  return new Date(dt).toLocaleString()
}

export default function JobsTable({ jobs, onRefresh }) {
  const [expanded, setExpanded] = useState(null)
  const [logs, setLogs] = useState({})

  async function toggleLogs(jobId) {
    if (expanded === jobId) { setExpanded(null); return }
    setExpanded(jobId)
    if (!logs[jobId]) {
      const data = await api.getJobLogs(jobId)
      setLogs(prev => ({ ...prev, [jobId]: data }))
    }
  }

  async function cancel(jobId) {
    await api.cancelJob(jobId)
    onRefresh()
  }

  return (
    <div className={styles.wrapper}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>ID</th><th>Type</th><th>Priority</th><th>Status</th>
            <th>Retries</th><th>Scheduled</th><th>Interval</th>
            <th>Created</th><th></th>
          </tr>
        </thead>
        <tbody>
          {jobs.map(job => (
            <>
              <tr key={job.id} className={styles.row} onClick={() => toggleLogs(job.id)}>
                <td className={styles.mono}>{job.id.slice(0, 8)}…</td>
                <td className={styles.mono}>{job.type}</td>
                <td><span className={`${styles.priority} ${styles[`p${job.priority}`]}`}>{PRIORITY_LABEL[job.priority]}</span></td>
                <td><span className={`${styles.badge} ${styles[STATUS_COLOR[job.status]]}`}>{job.status}</span></td>
                <td className={styles.center}>{job.retry_count}/{job.max_retries}</td>
                <td className={styles.mono}>{fmt(job.scheduled_at)}</td>
                <td className={styles.mono}>{job.recurring_interval ?? '—'}</td>
                <td className={styles.mono}>{fmt(job.created_at)}</td>
                <td onClick={e => e.stopPropagation()}>
                  {['pending', 'processing'].includes(job.status) && (
                    <button className={styles.cancelBtn} onClick={() => cancel(job.id)}>Cancel</button>
                  )}
                </td>
              </tr>
              {expanded === job.id && (
                <tr key={`${job.id}-logs`} className={styles.logRow}>
                  <td colSpan={9}>
                    <div className={styles.logBox}>
                      {job.last_error && (
                        <div className={styles.errorBanner}>{job.last_error}</div>
                      )}
                      <div className={styles.logTitle}>Audit log</div>
                      {(logs[job.id] ?? []).map(l => (
                        <div key={l.id} className={styles.logEntry}>
                          <span className={styles.logTime}>{fmt(l.created_at)}</span>
                          <span className={`${styles.logEvent} ${styles[l.event] ?? ''}`}>{l.event}</span>
                          <span className={styles.logMsg}>{l.message}</span>
                        </div>
                      ))}
                    </div>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
      {jobs.length === 0 && <div className={styles.empty}>No jobs found.</div>}
    </div>
  )
}
