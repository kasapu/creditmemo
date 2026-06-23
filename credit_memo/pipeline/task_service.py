"""In-memory task tracking + HITL approval gates.

A module-level singleton (resets on server restart). Each task owns an
``asyncio.Event`` used as the human-in-the-loop approval gate.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(BaseModel):
    task_id: UUID
    task_status_log: str = "Queued"
    task_complete_percentage: float = 0.0
    is_complete: bool = False
    awaiting_approval: bool = False
    result: Optional[dict] = None
    error: Optional[str] = None
    created_timestamp: datetime = Field(default_factory=_now)
    updated_timestamp: datetime = Field(default_factory=_now)


class ReportTaskService:
    def __init__(self) -> None:
        self._task: Dict[UUID, TaskStatus] = {}
        self._approval_events: Dict[UUID, asyncio.Event] = {}

    def create_task(self) -> TaskStatus:
        task_id = uuid4()
        status = TaskStatus(task_id=task_id)
        self._task[task_id] = status
        return status

    def get(self, task_id: UUID) -> Optional[TaskStatus]:
        return self._task.get(task_id)

    def update(self, task_id: UUID, *, status_log: Optional[str] = None,
               percentage: Optional[float] = None, is_complete: Optional[bool] = None,
               awaiting_approval: Optional[bool] = None,
               result: Optional[dict] = None) -> None:
        task = self._task.get(task_id)
        if not task:
            return
        if status_log is not None:
            task.task_status_log = status_log
        if percentage is not None:
            task.task_complete_percentage = percentage
        if is_complete is not None:
            task.is_complete = is_complete
        if awaiting_approval is not None:
            task.awaiting_approval = awaiting_approval
        if result is not None:
            task.result = result
        task.updated_timestamp = _now()

    def mark_failed(self, task_id: UUID, error: str) -> None:
        task = self._task.get(task_id)
        if not task:
            return
        task.error = error
        task.task_status_log = f"Failed: {error}"
        task.is_complete = True
        task.awaiting_approval = False
        task.updated_timestamp = _now()

    # --- HITL gate -----------------------------------------------------
    def create_approval_gate(self, task_id: UUID) -> asyncio.Event:
        event = asyncio.Event()
        self._approval_events[task_id] = event
        return event

    def approve(self, task_id: UUID) -> bool:
        """Release the gate. Returns False if no pending gate exists."""
        event = self._approval_events.get(task_id)
        if not event or event.is_set():
            return False
        event.set()
        return True

    def has_pending_gate(self, task_id: UUID) -> bool:
        event = self._approval_events.get(task_id)
        return bool(event and not event.is_set())


@lru_cache(maxsize=1)
def get_task_service() -> ReportTaskService:
    return ReportTaskService()
