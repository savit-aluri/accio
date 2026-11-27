"""The web server: invite-code check, budget, shared results and the search page."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import anthropic
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .access import AttemptLimiter, FriendDirectory
from .finder import DealFinder
from .jobs import AlreadySearching, JobManager
from .settings import Friend, Settings
from .store import BudgetExceeded, Database, DealCache, QueryKey, SpendLedger

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC = Path(__file__).resolve().parent / "static"

settings = Settings.load()
db = Database(settings.data_dir / "accio.db", settings.database_url)
directory = FriendDirectory(settings.friends)
limiter = AttemptLimiter()
ledger = SpendLedger(db, settings.timezone)
cache = DealCache(db, settings.cache_hours)
# Organization-wide API keys must name a workspace on every request.
_workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
_client_options = {"default_headers": {"anthropic-workspace-id": _workspace}} if _workspace else {}
finder = DealFinder(anthropic.AsyncAnthropic(max_retries=2, **_client_options), model=settings.model)
jobs = JobManager(finder, cache, ledger, settings)

app = FastAPI(title="Accio", docs_url=None, redoc_url=None, openapi_url=None)

if not os.environ.get("ANTHROPIC_API_KEY"):
    logging.getLogger("accio").warning("ANTHROPIC_API_KEY is not set: add it to .env, or searches will fail.")
if not settings.friends:
    logging.getLogger("accio").warning("No friends in friends.toml yet: run python manage.py add-friend NAME.")


def current_friend(request: Request, x_access_code: str | None = Header(default=None)) -> Friend:
    # Behind a Cloudflare tunnel every request arrives from 127.0.0.1, so use the visitor's
    # address Cloudflare passes along. The server only listens on 127.0.0.1, so only the
    # tunnel (or you, locally) can reach it and set this header.
    client_id = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
    if limiter.blocked(client_id):
        raise HTTPException(429, "Too many wrong codes. Wait 10 minutes and try again.")
    friend = directory.lookup(x_access_code)
    if friend is None:
        limiter.record_failure(client_id)
        raise HTTPException(401, "That invite code isn't on the list. Check it with whoever sent you the link.")
    return friend


def budget(friend: Friend) -> dict:
    spent = ledger.spent(friend.name)
    site_spent = ledger.spent()
    return {
        "spent": round(spent, 2),
        "cap": friend.daily_cap,
        "remaining": round(max(0.0, friend.daily_cap - spent), 2),
        "site_remaining": round(max(0.0, settings.daily_cap_site - site_spent), 2),
        "can_search": friend.daily_cap - spent >= ledger.MIN_TO_START
        and settings.daily_cap_site - site_spent >= ledger.MIN_TO_START,
    }


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=80)
    refresh: bool = False


@app.get("/healthz")
def health() -> dict:
    return {"ok": True}


@app.get("/")
def page() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/me")
def me(friend: Friend = Depends(current_friend)) -> dict:
    return {"name": friend.name, "budget": budget(friend), "cache_hours": settings.cache_hours}


@app.get("/api/recent")
def recent(friend: Friend = Depends(current_friend)) -> dict:
    return {
        "searches": [
            {"key": r.key, "query": r.query, "age_minutes": r.age_minutes, "deals": len(r.payload.get("deals", []))}
            for r in cache.recent()
        ]
    }


@app.get("/api/results/{key}")
def saved_result(key: str, friend: Friend = Depends(current_friend)) -> dict:
    hit = cache.get(key)
    if hit is None:
        raise HTTPException(404, "That search has expired. Search it again to get fresh prices.")
    return {"status": "done", "cached": True, "key": hit.key, "query": hit.query,
            "age_minutes": hit.age_minutes, "result": hit.payload, "cost": 0, "budget": budget(friend)}


@app.post("/api/search")
async def search(body: SearchRequest, friend: Friend = Depends(current_friend)) -> dict:
    query = QueryKey.display(body.query)
    key = QueryKey.make(query)
    if not key:
        raise HTTPException(400, "Add the kind of product you want, like air fryer or walking shoes.")

    if not body.refresh:
        hit = cache.get(key)
        if hit is not None:
            return {"status": "done", "cached": True, "key": hit.key, "query": hit.query,
                    "age_minutes": hit.age_minutes, "result": hit.payload, "cost": 0, "budget": budget(friend)}

    try:
        job, shared = jobs.start(friend, key, query)
    except AlreadySearching:
        raise HTTPException(409, "You already have a search running. Wait for it to finish.")
    except BudgetExceeded as exc:
        if exc.scope == "site":
            raise HTTPException(403, "The site has reached today's spending limit. Saved searches still work for free.")
        raise HTTPException(
            403, f"You've used today's ${exc.cap:.2f}. Searches other people already ran are still free to open."
        )
    return {**job.view(), "shared": shared, "budget": budget(friend)}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, friend: Friend = Depends(current_friend)) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "That search is no longer running. Search again.")
    view = job.view()
    if job.friend != friend.name:
        view["cost"] = 0  # someone else paid for it
    return {**view, "budget": budget(friend)}
