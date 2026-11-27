"""Invite codes: who a code belongs to, and a brake on people guessing codes."""

from __future__ import annotations

import hmac
import logging
import time
import tomllib
from collections import defaultdict, deque
from pathlib import Path

from .settings import Friend, Settings

log = logging.getLogger("accio.access")


class FriendDirectory:
    """Looks up the friend an invite code belongs to.

    Watches friends.toml, so adding a friend or turning a code off takes effect
    on the running site without a restart (and without changing its public link).
    """

    def __init__(self, friends: tuple[Friend, ...], source: Path | None = None):
        self._friends = friends
        self._source = source
        self._mtime = self._stat()

    def _stat(self) -> float | None:
        try:
            return self._source.stat().st_mtime if self._source else None
        except OSError:
            return None

    def refresh(self) -> None:
        mtime = self._stat()
        if mtime is None or mtime == self._mtime:
            return
        try:
            friends = Settings.parse_friends(tomllib.loads(self._source.read_text()))
        except (OSError, ValueError, tomllib.TOMLDecodeError, KeyError) as exc:
            log.warning("friends.toml changed but couldn't be read, keeping the old list: %s", exc)
            return
        self._friends, self._mtime = friends, mtime
        log.info("friends.toml reloaded: %d active codes", len(friends))

    def lookup(self, code: str | None) -> Friend | None:
        if not code:
            return None
        given = code.strip().lower().encode()
        match = None
        # Compare against every code so the time taken doesn't reveal near misses.
        for friend in self._friends:
            if hmac.compare_digest(friend.code.lower().encode(), given):
                match = friend
        return match


class AttemptLimiter:
    """Blocks a client for a while after too many wrong codes."""

    def __init__(self, max_failures: int = 10, window_seconds: int = 600):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, client_id: str) -> deque[float]:
        cutoff = time.monotonic() - self.window_seconds
        attempts = self._failures[client_id]
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        return attempts

    def blocked(self, client_id: str) -> bool:
        return len(self._trim(client_id)) >= self.max_failures

    def record_failure(self, client_id: str) -> None:
        self._trim(client_id).append(time.monotonic())
