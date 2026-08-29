import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import settings
from .database import SessionLocal
from .worker import run_until_empty


logger = logging.getLogger(__name__)


@dataclass
class WorkerRuntimeState:
    running: bool = False
    last_run_at: datetime | None = None
    last_error: str | None = None
    processed_total: int = 0


worker_runtime = WorkerRuntimeState()


def run_inline_worker_cycle() -> int:
    """Drain one bounded batch using a fresh database session."""
    with SessionLocal() as db:
        processed = run_until_empty(db, limit=settings.inline_worker_batch_size)
    worker_runtime.last_run_at = datetime.now(timezone.utc)
    worker_runtime.last_error = None
    worker_runtime.processed_total += processed
    return processed


async def inline_worker_loop(stop_event: asyncio.Event) -> None:
    worker_runtime.running = True
    try:
        while not stop_event.is_set():
            try:
                await asyncio.to_thread(run_inline_worker_cycle)
            except Exception as exc:  # keep API alive; event retry state remains auditable
                worker_runtime.last_run_at = datetime.now(timezone.utc)
                worker_runtime.last_error = str(exc)[:500]
                logger.exception("PoopSense inline worker cycle failed")
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=settings.inline_worker_poll_seconds
                )
            except TimeoutError:
                pass
    finally:
        worker_runtime.running = False
