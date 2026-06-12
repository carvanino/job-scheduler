const API = '/api/v1'

export const api = {
  getStats:    () => fetch(`${API}/jobs/stats`).then(r => r.json()),
  listJobs:    (status) => fetch(`${API}/jobs?${status ? `status=${status}&` : ''}limit=100`).then(r => r.json()),
  createJob:   (body) => fetch(`${API}/jobs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json()),
  cancelJob:   (id) => fetch(`${API}/jobs/${id}/cancel`, { method: 'POST' }).then(r => r.json()),
  getJobLogs:  (id) => fetch(`${API}/jobs/${id}/logs`).then(r => r.json()),
  listDLQ:     () => fetch(`${API}/dlq`).then(r => r.json()),
  retryDLQ:    (id) => fetch(`${API}/dlq/${id}/retry`, { method: 'POST' }).then(r => r.json()),
}
