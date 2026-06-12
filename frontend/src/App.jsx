import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import Dashboard from './components/Dashboard'
import JobsTable from './components/JobsTable'
import CreateJobForm from './components/CreateJobForm'
import DLQ from './components/DLQ'
import { useWebSocket } from './hooks/useWebSocket'
import './App.css'

const TABS = ['All Jobs', 'Create Job', 'Dead-Letter Queue']

export default function App() {
  const [tab, setTab] = useState('All Jobs')
  const [stats, setStats] = useState(null)
  const [jobs, setJobs] = useState([])
  const [dlqEntries, setDlqEntries] = useState([])
  const [statusFilter, setStatusFilter] = useState('')
  const [dlqAlert, setDlqAlert] = useState(null)

  const loadStats = useCallback(async () => {
    const data = await api.getStats()
    setStats(data)
  }, [])

  const loadJobs = useCallback(async () => {
    const data = await api.listJobs(statusFilter)
    setJobs(Array.isArray(data) ? data : [])
  }, [statusFilter])

  const loadDLQ = useCallback(async () => {
    const data = await api.listDLQ()
    setDlqEntries(Array.isArray(data) ? data : [])
  }, [])

  useEffect(() => { loadStats(); loadJobs(); loadDLQ() }, [loadStats, loadJobs, loadDLQ])

  // WebSocket live updates
  const onMessage = useCallback((msg) => {
    if (msg.type === 'job_update') {
      loadJobs()
      loadStats()
    }
    if (msg.type === 'stats_update') {
      setStats(msg.data)
    }
    if (msg.type === 'dlq_alert') {
      setDlqAlert(msg.data)
      loadDLQ()
      loadStats()
    }
  }, [loadJobs, loadStats, loadDLQ])

  const { connected } = useWebSocket(onMessage)

  function refresh() { loadJobs(); loadStats(); loadDLQ() }

  return (
    <div className="layout">
      <header className="header">
        <div className="header-left">
          <span className="logo">JobScheduler</span>
          <span className={`ws-dot ${connected ? 'live' : 'dead'}`} title={connected ? 'Live' : 'Reconnecting…'} />
          <span className="ws-label">{connected ? 'Live' : 'Reconnecting…'}</span>
        </div>
        <nav className="tabs">
          {TABS.map(t => (
            <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>{t}</button>
          ))}
        </nav>
      </header>

      {dlqAlert && (
        <div className="dlq-alert">
          DLQ threshold exceeded — {dlqAlert.count} failed jobs (threshold: {dlqAlert.threshold}).
          <button onClick={() => setDlqAlert(null)}>×</button>
        </div>
      )}

      <main className="main">
        <section className="section">
          <h2 className="section-title">Overview</h2>
          <Dashboard stats={stats} />
        </section>

        {tab === 'All Jobs' && (
          <section className="section">
            <div className="section-row">
              <h2 className="section-title">Jobs</h2>
              <div className="filter-row">
                <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); }}>
                  <option value="">All statuses</option>
                  {['pending','processing','completed','failed','cancelled'].map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
                <button className="refresh-btn" onClick={refresh}>Refresh</button>
              </div>
            </div>
            <JobsTable jobs={jobs} onRefresh={refresh} />
          </section>
        )}

        {tab === 'Create Job' && (
          <section className="section">
            <h2 className="section-title">Create Job</h2>
            <p className="section-sub">
              Create a webhook delivery job. Set priority, schedule, and optional recurring interval.
            </p>
            <CreateJobForm onCreated={() => { setTab('All Jobs'); refresh() }} />
          </section>
        )}

        {tab === 'Dead-Letter Queue' && (
          <section className="section">
            <h2 className="section-title">Dead-Letter Queue</h2>
            <p className="section-sub">
              Jobs that exhausted all retries. Inspect the error, fix the underlying issue, and manually retry.
            </p>
            <DLQ entries={dlqEntries} onRefresh={() => { loadDLQ(); loadStats() }} />
          </section>
        )}
      </main>
    </div>
  )
}
