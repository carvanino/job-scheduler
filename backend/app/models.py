"""
SQLAlchemy models for the job scheduler.

Tables:
  jobs              — every job that enters the system
  job_dependencies  — DAG edges (job_id depends on depends_on_id)
  dead_letter_jobs  — jobs that exhausted all retries
  job_logs          — structured audit trail of every significant event
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Core fields
    type = Column(String(100), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    priority = Column(Integer, nullable=False, default=2)  # 1=High 2=Medium 3=Low
    status = Column(String(20), nullable=False, default="pending")

    # Retry tracking
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    last_error = Column(Text, nullable=True)

    # Scheduling
    scheduled_at = Column(DateTime(timezone=True), nullable=True)   # future run time
    recurring_interval = Column(String(50), nullable=True)           # every_1_minute etc.
    next_run_at = Column(DateTime(timezone=True), nullable=True)     # next scheduled run

    # Locking (duplicate protection)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    locked_by = Column(String(100), nullable=True)

    # Result
    result = Column(JSONB, nullable=True)

    # Starvation prevention — scheduler uses this field, not priority directly
    effective_priority = Column(Float, nullable=False, default=2.0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    dependencies = relationship(
        "JobDependency",
        foreign_keys="JobDependency.job_id",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    depends_on = relationship(
        "JobDependency",
        foreign_keys="JobDependency.depends_on_id",
        back_populates="dependency",
    )
    logs = relationship("JobLog", back_populates="job", cascade="all, delete-orphan")
    dlq_entry = relationship("DeadLetterJob", back_populates="job", uselist=False)


class JobDependency(Base):
    """
    DAG edge: job_id cannot run until depends_on_id is completed.
    """
    __tablename__ = "job_dependencies"
    __table_args__ = (UniqueConstraint("job_id", "depends_on_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    depends_on_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    job = relationship("Job", foreign_keys=[job_id], back_populates="dependencies")
    dependency = relationship("Job", foreign_keys=[depends_on_id], back_populates="depends_on")


class DeadLetterJob(Base):
    """
    Jobs that have exhausted all retries land here.
    Engineers can inspect the error and manually re-queue.
    """
    __tablename__ = "dead_letter_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, unique=True)
    error = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False)
    moved_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    retried_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("Job", back_populates="dlq_entry")


class JobLog(Base):
    """
    Immutable audit trail. One row per significant event.
    Events: created / started / retry / failed / cancelled / completed / dlq_moved / dlq_retry
    """
    __tablename__ = "job_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    event = Column(String(50), nullable=False)
    message = Column(Text, nullable=True)
    data = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    job = relationship("Job", back_populates="logs")
