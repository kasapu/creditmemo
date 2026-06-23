"""FastAPI routes: task lifecycle, SSE streaming, HITL approval, KPIs."""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..config import get_config
from ..infra import sec_fetcher, storage
from ..pipeline import kpi_service
from ..pipeline.pipeline_service import run_pipeline
from ..pipeline.task_service import get_task_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analysis")


# ------------------------------------------------------------------ #
#  Task lifecycle                                                    #
# ------------------------------------------------------------------ #
@router.post("/{ticker}/report/task")
async def start_task(ticker: str, fiscal_year: str | None = None,
                     fiscal_period: str | None = None):
    svc = get_task_service()
    task = svc.create_task()
    asyncio.create_task(run_pipeline(task.task_id, ticker, fiscal_year, fiscal_period))
    return {"task_id": str(task.task_id)}


@router.get("/report/task/{task_id}")
async def get_task(task_id: UUID):
    task = get_task_service().get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task.model_dump(mode="json")


@router.post("/report/task/{task_id}/approve")
async def approve_task(task_id: UUID):
    svc = get_task_service()
    task = svc.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task_expired")
    if not task.awaiting_approval:
        raise HTTPException(status_code=409, detail="not_pending")
    if not svc.approve(task_id):
        raise HTTPException(status_code=409, detail="not_pending")
    return {"status": "approved"}


# ------------------------------------------------------------------ #
#  SSE stream                                                        #
# ------------------------------------------------------------------ #
@router.get("/report/task/{task_id}/stream")
async def stream_task(task_id: UUID):
    svc = get_task_service()

    async def event_gen():
        last_pct = -1.0
        last_status = ""
        ping = 0
        while True:
            task = svc.get(task_id)
            if not task:
                yield _sse("error", {"message": "task_not_found"})
                return

            changed = (task.task_complete_percentage != last_pct
                       or task.task_status_log != last_status)
            if changed:
                last_pct = task.task_complete_percentage
                last_status = task.task_status_log
                payload = {
                    "task_id": str(task_id),
                    "task_status_log": task.task_status_log,
                    "task_complete_percentage": task.task_complete_percentage,
                    "awaiting_approval": task.awaiting_approval,
                }
                if task.awaiting_approval and task.result:
                    payload["result"] = task.result
                yield _sse("update", payload)

            if task.error:
                yield _sse("error", {"message": task.error})
                return
            if task.is_complete and not task.awaiting_approval:
                yield _sse("complete", {"task_id": str(task_id), "result": task.result})
                return

            await asyncio.sleep(2)
            ping += 2
            if ping >= 30:
                ping = 0
                yield ": ping\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ------------------------------------------------------------------ #
#  Companies + KPIs                                                  #
# ------------------------------------------------------------------ #
@router.get("/cached-companies")
async def cached_companies():
    return {"companies": storage.list_cached_companies()}


@router.get("/{ticker}/kpis")
async def get_kpis(ticker: str, fiscal_year: str | None = None,
                   fiscal_period: str | None = None):
    sec_data = storage.load_sec_data(ticker)
    if not sec_data:
        sec_data = await asyncio.to_thread(sec_fetcher.get_quarterly_financials, ticker)
        storage.save_sec_data(ticker, sec_data)
    kpi_data = await asyncio.to_thread(
        kpi_service.run_kpi_analysis, ticker, fiscal_year, fiscal_period, sec_data)
    return kpi_data
