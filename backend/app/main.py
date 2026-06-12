"""
FastAPI application entry point.

Startup:
  1. Creates all DB tables
  2. Starts WORKER_COUNT worker tasks in the background
  3. Each worker shares a single IndexedPriorityQueue instance
     (the IPQ is thread-safe via asyncio — workers run in the same event loop)

Shutdown:
  1. Cancels all worker tasks cleanly
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.dlq import router as dlq_router
from app.api.jobs import router as jobs_router
from app.api.ws import ws_manager
from app.config import settings
from app.database import Base, engine
from app.logger import configure_logging, get_logger
from app.scheduler.indexed_pq import IndexedPriorityQueue
from app.worker.worker import Worker

configure_logging()
log = get_logger(__name__)

# Shared indexed priority queue — all workers use the same instance
ipq = IndexedPriorityQueue()
_worker_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("app.db_ready")

    # Start workers
    for i in range(settings.WORKER_COUNT):
        worker_id = f"worker-{i + 1}"
        worker = Worker(
            worker_id=worker_id,
            ipq=ipq,
            ws_broadcast=ws_manager.broadcast,
        )
        task = asyncio.create_task(worker.start(), name=worker_id)
        _worker_tasks.append(task)
    log.info("app.workers_started", count=settings.WORKER_COUNT)

    yield

    # Shutdown
    for task in _worker_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    log.info("app.workers_stopped")


app = FastAPI(
    title="Job Scheduler API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router, prefix="/api/v1")
app.include_router(dlq_router, prefix="/api/v1")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            # Keep connection alive — workers push updates via ws_manager.broadcast
            await ws.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(ws)


@app.get("/health")
async def health():
    return {"status": "ok", "workers": settings.WORKER_COUNT}
