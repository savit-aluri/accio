"""Runs searches in the background so the page can poll, and shares one search between friends."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime

from .finder import DealFinder, FinderError
from .settings import Friend, Settings
from .store import DealCache, SpendLedger

log = logging.getLogger("accio.jobs")


class AlreadySearching(Exception):
    """This friend already has a search running."""


@dataclass
class Job:
    id: str
    key: str
    query: str
    friend: str
    started: float = field(default_factory=time.time)
    status: str = "running"  # running | done | error
    result: dict | None = None
    error: str | None = None
    cost: float = 0.0

    def view(self) -> dict:
        return {
            "job_id": self.id,
            "status": self.status,
            "key": self.key,
            "query": self.query,
            "seconds": int(time.time() - self.started),
            "result": self.result,
            "error": self.error,
            "cost": round(self.cost, 4),
        }


class JobManager:
    """Starts searches, records their cost, and saves their results for everyone."""

    KEEP_FINISHED_SECONDS = 15 * 60

    def __init__(self, finder: DealFinder, cache: DealCache, ledger: SpendLedger, settings: Settings):
        self._finder = finder
        self._cache = cache
        self._ledger = ledger
        self._settings = settings
        self._jobs: dict[str, Job] = {}
        self._running_by_key: dict[str, Job] = {}
        self._running_by_friend: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()

    def get(self, job_id: str) -> Job | None:
        self._forget_old()
        return self._jobs.get(job_id)

    def running_for_key(self, key: str) -> Job | None:
        return self._running_by_key.get(key)

    def start(self, friend: Friend, key: str, query: str) -> tuple[Job, bool]:
        """Returns the job and whether it was shared with a search someone else already started."""
        existing = self._running_by_key.get(key)
        if existing:
            return existing, True
        if friend.name in self._running_by_friend:
            raise AlreadySearching()
        self._ledger.check(friend, self._settings.daily_cap_site)

        job = Job(id=secrets.token_urlsafe(9), key=key, query=query, friend=friend.name)
        self._jobs[job.id] = job
        self._running_by_key[key] = job
        self._running_by_friend[friend.name] = job
        task = asyncio.create_task(self._run(job, friend))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job, False

    async def _run(self, job: Job, friend: Friend) -> None:
        today = datetime.now(self._settings.timezone).date()
        try:
            found = await self._finder.find(job.query, today)
            job.cost = found.cost.dollars
            self._ledger.record(friend, job.cost, job.query)
            self._cache.put(job.key, job.query, found.report, job.cost)
            job.result = found.report
            job.status = "done"
            log.info(
                "search %r by %s cost $%.4f (in=%d out=%d searches=%d)",
                job.query, friend.name, job.cost, found.cost.input_tokens,
                found.cost.output_tokens, found.cost.web_searches,
            )
        except FinderError as exc:
            job.cost = exc.cost.dollars
            if job.cost:
                self._ledger.record(friend, job.cost, job.query + " (failed)")
            job.status, job.error = "error", str(exc)
            log.warning("search %r by %s failed: %s (cost $%.4f)", job.query, friend.name, exc, job.cost)
        except Exception:  # keep the server alive whatever happens in one search
            log.exception("search %r crashed", job.query)
            job.status, job.error = "error", "Something went wrong on the server. Try again."
        finally:
            self._running_by_key.pop(job.key, None)
            self._running_by_friend.pop(friend.name, None)

    def _forget_old(self) -> None:
        cutoff = time.time() - self.KEEP_FINISHED_SECONDS
        for job_id in [j.id for j in self._jobs.values() if j.status != "running" and j.started < cutoff]:
            self._jobs.pop(job_id, None)
