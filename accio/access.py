"""Invite codes: who a code belongs to, and a brake on people guessing codes."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque

from .settings import Friend


class FriendDirectory:
    """Looks up the friend an invite code belongs to."""

    def __init__(self, friends: tuple[Friend, ...]):
        self._friends = friends

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
