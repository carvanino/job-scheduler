from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── Job schemas ──────────────────────────────────────────────────


class JobCreate(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=2, ge=1, le=3)
    scheduled_at: datetime | None = None
    recurring_interval: str | None = None
    dependency_ids: list[UUID] = Field(default_factory=list)


class JobResponse(BaseModel):
    id: UUID
    type: str
    payload: dict[str, Any]
    priority: int
    status: str
    retry_count: int
    max_retries: int
    last_error: str | None
    scheduled_at: datetime | None
    recurring_interval: str | None
    next_run_at: datetime | None
    effective_priority: float
    result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class JobStats(BaseModel):
    pending: int
    processing: int
    completed: int
    failed: int
    cancelled: int
    total: int
    dlq: int


# ── DLQ schemas ──────────────────────────────────────────────────


class DLQEntry(BaseModel):
    id: UUID
    job_id: UUID
    error: str | None
    retry_count: int
    moved_at: datetime
    retried_at: datetime | None
    job: JobResponse

    model_config = {"from_attributes": True}


# ── Log schemas ──────────────────────────────────────────────────


class JobLogResponse(BaseModel):
    id: UUID
    job_id: UUID
    event: str
    message: str | None
    data: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── WebSocket message schemas ─────────────────────────────────────


class WSMessage(BaseModel):
    type: str
    data: dict[str, Any]
