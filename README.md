# Job Scheduler

A background job scheduler with a working UI. Jobs are created, queued, processed, and tracked. Workers run independently. The system handles failure automatically.

---

## Stack

| Layer      | Tech                                      |
|------------|-------------------------------------------|
| Backend    | Python 3.12, FastAPI, SQLAlchemy (async)  |
| Database   | PostgreSQL                                |
| Workers    | asyncio background tasks                  |
| Queue      | In-memory IndexedPriorityQueue + MinHeap  |
| Real-time  | WebSockets                                |
| Frontend   | React 18, Vite                            |

---

## Setup

### Requirements

- Python 3.12+
- Node.js 18+
- PostgreSQL running locally

### Backend

```bash
cd backend

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL to your PostgreSQL instance

# Start the server (tables are created automatically on startup)
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# Opens at http://localhost:5173
```

### Production build

```bash
cd frontend
npm run build
# Static files in dist/ — serve behind Nginx
```

---

## API Endpoints

### Jobs

| Method | Path                      | Description                        |
|--------|---------------------------|------------------------------------|
| POST   | /api/v1/jobs              | Create a job                       |
| GET    | /api/v1/jobs              | List jobs (filter by ?status=)     |
| GET    | /api/v1/jobs/stats        | Job counts by status               |
| GET    | /api/v1/jobs/:id          | Get a single job                   |
| POST   | /api/v1/jobs/:id/cancel   | Cancel a job                       |
| GET    | /api/v1/jobs/:id/logs     | Get audit log for a job            |

### Dead-Letter Queue

| Method | Path                    | Description                |
|--------|-------------------------|----------------------------|
| GET    | /api/v1/dlq             | List all DLQ entries       |
| POST   | /api/v1/dlq/:id/retry   | Manually retry a DLQ job   |

### WebSocket

```
ws://localhost:8000/ws
```

Messages pushed to the client:
```json
{ "type": "job_update",   "data": { "job_id": "...", "status": "processing" } }
{ "type": "stats_update", "data": { "pending": 4, "processing": 1, ... } }
{ "type": "dlq_alert",    "data": { "count": 10, "threshold": 10 } }
```

### Health

```
GET /health
```

---

## Creating a Webhook Job

```bash
curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "type": "webhook",
    "priority": 1,
    "payload": {
      "url": "https://webhook.site/your-id",
      "event": "payment_confirmed",
      "data": { "order_id": "ORD-001", "amount": 45000 }
    }
  }' | python3 -m json.tool
```

### Scheduled job (runs at a future time)

```bash
curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "type": "webhook",
    "priority": 2,
    "scheduled_at": "2026-06-15T10:00:00Z",
    "payload": { "url": "https://webhook.site/your-id", "event": "scheduled_event" }
  }'
```

### Recurring job

```bash
curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "type": "webhook",
    "priority": 2,
    "recurring_interval": "every_5_minutes",
    "payload": { "url": "https://webhook.site/your-id", "event": "heartbeat" }
  }'
```

### DAG workflow — job B depends on job A

```bash
# Step 1: create job A
JOB_A=$(curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{ "type": "webhook", "priority": 1, "payload": { "url": "https://webhook.site/your-id", "event": "generate_report" } }')
echo $JOB_A | python3 -m json.tool

# Step 2: create job B with dependency on A
JOB_A_ID=$(echo $JOB_A | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d "{
    \"type\": \"webhook\",
    \"priority\": 1,
    \"payload\": { \"url\": \"https://webhook.site/your-id\", \"event\": \"send_email\" },
    \"dependency_ids\": [\"$JOB_A_ID\"]
  }" | python3 -m json.tool
```

Job B will not run until job A has status `completed`.

### Cancel a job

```bash
curl -s -X POST http://localhost:8000/api/v1/jobs/{job-id}/cancel
```

### View DLQ and manually retry

```bash
# List DLQ entries
curl -s http://localhost:8000/api/v1/dlq | python3 -m json.tool

# Retry a specific DLQ entry
curl -s -X POST http://localhost:8000/api/v1/dlq/{dlq-id}/retry
```

---

## Architecture

```
Browser (React)
     |  WebSocket (live updates)
     |  REST (create / list / cancel)
     ↓
FastAPI (app/main.py)
     |
     |── Jobs API (/api/v1/jobs)
     |── DLQ API  (/api/v1/dlq)
     |── WebSocket (/ws) ← broadcasts to all connected clients
     |
     └── Worker Pool (2 workers, asyncio tasks)
              |
              | polls every 500ms
              ↓
         IndexedPriorityQueue (in-memory)
              |
              | ordered by (effective_priority, scheduled_at, created_at)
              ↓
         PostgreSQL
              |
              |── jobs               (status, retry_count, payload, ...)
              |── job_dependencies   (DAG edges)
              |── dead_letter_jobs   (exhausted retries)
              └── job_logs           (audit trail)
```

### Write path (POST /jobs)

```
Client → FastAPI → INSERT jobs row (status=pending)
                 → INSERT job_logs row (event=created)
                 → WebSocket broadcast (job_update)
```

### Worker tick (every 500ms)

```
1. SELECT pending jobs WHERE scheduled_at <= now → push into IndexedPQ
2. Run starvation check on IndexedPQ → update_priority for waiting jobs
3. Peek at highest-priority entry
4. Check DAG: all dependencies completed? If not, skip
5. SELECT FOR UPDATE SKIP LOCKED → lock the row (prevents duplicate pickup)
6. Mark status=processing
7. Execute webhook handler (real HTTP POST)
8. On success → mark completed, schedule next run if recurring
9. On transient failure → increment retry_count, re-queue with backoff
10. On 4xx → mark failed immediately (terminal, no retry)
11. On exhausted retries → INSERT dead_letter_jobs
12. Broadcast status change via WebSocket
```

---

## Scheduling Algorithms

### Primary: MinHeap

A binary min-heap stored as a flat array. Jobs are ordered by:
1. `effective_priority` — lower number = more urgent (1=High, 2=Medium, 3=Low)
2. `scheduled_at` — earlier time runs first
3. `created_at` — FIFO tiebreak

Operations:
- Push: O(log n) — append, bubble up
- Pop:  O(log n) — swap root with last, bubble down
- Peek: O(1)

### Alternative: Indexed Priority Queue

Extends the MinHeap with a dictionary `{ job_id → heap_position }`. This makes two operations significantly faster:

| Operation          | MinHeap     | IndexedPQ    |
|--------------------|-------------|--------------|
| `update_priority`  | O(n)        | O(log n)     |
| `remove by id`     | O(n)        | O(log n)     |
| `push` / `pop`     | O(log n)    | O(log n)     |

`update_priority` is the core operation for starvation prevention — it runs every 30 seconds on all pending jobs. With a plain heap this is O(n) per update (scan to find the job, then fix order). With the indexed PQ it is O(1) lookup + O(log n) bubble.

### Benchmark

```bash
cd backend
python benchmark.py
```

---

## Starvation Prevention

Low-priority jobs cannot wait forever. The scheduler boosts `effective_priority` based on wait time using linear interpolation:

```
effective_priority = original - (original - 1.0) * (minutes_waiting / 15)
```

| Condition                     | What happens                          |
|-------------------------------|---------------------------------------|
| Low (p=3), waiting > 5 min    | Boost begins, approaches p=2          |
| Medium (p=2), waiting > 10 min| Boost begins, approaches p=1          |
| Any job, waiting > 15 min     | Effective priority reaches 1.0 (High) |

---

## Retry Backoff

Failed jobs retry up to 3 times with exponential backoff and jitter:

| Attempt | Base delay | Jitter range | Actual range |
|---------|------------|--------------|--------------|
| 1       | 1s         | ×[0.8, 1.2)  | 0.8–1.2s     |
| 2       | 5s         | ×[0.8, 1.2)  | 4–6s         |
| 3       | 25s        | ×[0.8, 1.2)  | 20–30s       |
| 4       | —          | —            | → DLQ        |

4xx HTTP responses are **terminal** — no retry. 5xx, timeouts, and network errors are **transient** — retry eligible.

---

## DLQ Alert Threshold

When the dead-letter queue reaches **10 jobs**, an alert is logged at ERROR level and a WebSocket `dlq_alert` event is broadcast to all connected UI clients. The threshold is configurable via `DLQ_ALERT_THRESHOLD` in `.env`.

---

## Cancellation

- **pending** jobs: immediately marked `cancelled`. Worker will not pick them up.
- **processing** jobs: marked `cancelled` in the DB. The current worker attempt runs to completion (the HTTP call is already in-flight). The worker checks status before re-queueing on failure — a cancelled job is not retried.

This is a best-effort, not an abort. Documented here and in the code.

---

## Duplicate Protection

Workers use `SELECT FOR UPDATE SKIP LOCKED` when locking a job:

```sql
SELECT * FROM jobs
WHERE id = $1 AND status = 'pending'
FOR UPDATE SKIP LOCKED
```

If two workers race for the same job, only one gets the lock. The other gets zero rows back and moves on. No two workers can process the same job at the same time.

---

## Nginx Configuration (VPS deployment)

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Frontend
    location / {
        root /var/www/job-scheduler;
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # WebSocket — must upgrade the connection
    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

---

## Structured Log Events

Every significant event is logged as a JSON object:

| Event               | Trigger                                      |
|---------------------|----------------------------------------------|
| `job.created`       | POST /jobs                                   |
| `job.started`       | Worker locks a job                           |
| `job.completed`     | Handler returns successfully                 |
| `job.retry_scheduled` | Transient failure, retry queued            |
| `job.terminal_failure` | 4xx response, no retry                    |
| `job.failed`        | Terminal failure or propagated DAG failure   |
| `job.cancelled`     | POST /jobs/:id/cancel                        |
| `job.dlq_moved`     | Retries exhausted                            |
| `dlq.retry_triggered` | POST /dlq/:id/retry                        |
| `dlq.threshold_exceeded` | DLQ crosses alert threshold            |
| `starvation.priority_boosted` | Job waiting too long               |
| `worker.started`    | Worker process begins                        |

Example log line:
```json
{
  "timestamp": "2026-06-01T10:23:41.123Z",
  "level": "info",
  "event": "job.completed",
  "job_id": "a3f1c2d4-...",
  "type": "webhook",
  "logger": "app.worker.worker"
}
```

---

## What I struggled with

> *(Your section — fill in)*

---

## What I learned

> *(Your section — fill in)*

---

## Resources consulted

> *(Your section — fill in)*

---

## Why this made me a better backend developer

> *(Your section — fill in)*
