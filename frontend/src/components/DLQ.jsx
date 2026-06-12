import { api } from '../api'
import styles from './DLQ.module.css'

function fmt(dt) {
  if (!dt) return '—'
  return new Date(dt).toLocaleString()
}

export default function DLQ({ entries, onRefresh }) {
  async function retry(dlqId) {
    await api.retryDLQ(dlqId)
    onRefresh()
  }

  if (!entries.length) {
    return <div className={styles.empty}>Dead-letter queue is empty.</div>
  }

  return (
    <div className={styles.list}>
      {entries.map(e => (
        <div key={e.id} className={styles.card}>
          <div className={styles.header}>
            <div>
              <span className={styles.jobType}>{e.job?.type ?? 'unknown'}</span>
              <span className={styles.jobId}>{e.job_id.slice(0, 8)}…</span>
            </div>
            <div className={styles.meta}>
              <span>Retries: <strong>{e.retry_count}</strong></span>
              <span>Moved: {fmt(e.moved_at)}</span>
              {e.retried_at && <span>Last retry: {fmt(e.retried_at)}</span>}
            </div>
          </div>
          <div className={styles.error}>{e.error ?? 'No error details'}</div>
          <div className={styles.payload}>
            <span className={styles.payloadLabel}>Payload</span>
            <pre>{JSON.stringify(e.job?.payload ?? {}, null, 2)}</pre>
          </div>
          <button className={styles.retryBtn} onClick={() => retry(e.id)}>
            Retry
          </button>
        </div>
      ))}
    </div>
  )
}
