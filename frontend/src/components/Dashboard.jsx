import styles from './Dashboard.module.css'

const CARDS = [
  { key: 'pending',    label: 'Pending',    color: 'yellow' },
  { key: 'processing', label: 'Processing', color: 'blue'   },
  { key: 'completed',  label: 'Completed',  color: 'green'  },
  { key: 'failed',     label: 'Failed',     color: 'red'    },
  { key: 'cancelled',  label: 'Cancelled',  color: 'muted'  },
  { key: 'dlq',        label: 'DLQ',        color: 'red'    },
]

export default function Dashboard({ stats }) {
  return (
    <div className={styles.grid}>
      {CARDS.map(c => (
        <div key={c.key} className={`${styles.card} ${styles[c.color]}`}>
          <span className={styles.value}>{stats?.[c.key] ?? 0}</span>
          <span className={styles.label}>{c.label}</span>
        </div>
      ))}
    </div>
  )
}
