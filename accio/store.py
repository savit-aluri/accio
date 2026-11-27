"""SQLite storage: what each friend spent today, and saved search results everyone can reuse."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .settings import Friend


class Database:
    """One SQLite file shared by the ledger and the cache."""

    def __init__(self, path: Path):
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS spend (
                id INTEGER PRIMARY KEY,
                friend TEXT NOT NULL,
                day TEXT NOT NULL,
                amount REAL NOT NULL,
                query TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS spend_day ON spend(day, friend);
            CREATE TABLE IF NOT EXISTS results (
                key TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                payload TEXT NOT NULL,
                cost REAL NOT NULL,
                created_at REAL NOT NULL,
                views INTEGER NOT NULL DEFAULT 0
            );
            """
        )


# ---------------------------------------------------------------- spending


class BudgetExceeded(Exception):
    def __init__(self, scope: str, spent: float, cap: float):
        self.scope = scope  # "friend" or "site"
        self.spent = spent
        self.cap = cap
        super().__init__(f"{scope} budget used: ${spent:.2f} of ${cap:.2f}")


class SpendLedger:
    """Records the real cost of every search and enforces the daily caps.

    A search may start while at least MIN_TO_START dollars remain, so a friend can
    end the day at most one search over their cap.
    """

    MIN_TO_START = 0.10

    def __init__(self, db: Database, tz: ZoneInfo):
        self._db = db
        self._tz = tz

    def today(self) -> str:
        return datetime.now(self._tz).date().isoformat()

    def spent(self, friend: str | None = None) -> float:
        sql = "SELECT COALESCE(SUM(amount), 0) FROM spend WHERE day = ?"
        args: list = [self.today()]
        if friend is not None:
            sql += " AND friend = ?"
            args.append(friend)
        with self._db.lock:
            return float(self._db.conn.execute(sql, args).fetchone()[0])

    def check(self, friend: Friend, site_cap: float) -> None:
        friend_spent = self.spent(friend.name)
        if friend.daily_cap - friend_spent < self.MIN_TO_START:
            raise BudgetExceeded("friend", friend_spent, friend.daily_cap)
        site_spent = self.spent()
        if site_cap - site_spent < self.MIN_TO_START:
            raise BudgetExceeded("site", site_spent, site_cap)

    def record(self, friend: Friend, amount: float, query: str) -> None:
        with self._db.lock:
            self._db.conn.execute(
                "INSERT INTO spend (friend, day, amount, query, created_at) VALUES (?, ?, ?, ?, ?)",
                (friend.name, self.today(), round(amount, 6), query, time.time()),
            )

    def report(self, days: int = 7) -> list[sqlite3.Row]:
        with self._db.lock:
            return self._db.conn.execute(
                "SELECT day, friend, COUNT(*) AS searches, SUM(amount) AS dollars FROM spend "
                "GROUP BY day, friend ORDER BY day DESC, dollars DESC LIMIT ?",
                (days * 50,),
            ).fetchall()


# ---------------------------------------------------------------- shared results

STOPWORDS = {
    "a", "an", "the", "for", "on", "of", "in", "to", "and", "or", "with", "my", "me", "some", "any",
    "deal", "deals", "black", "friday", "cyber", "monday", "sale", "sales", "best", "good", "great",
    "cheap", "cheapest", "discount", "discounts", "offer", "offers", "2026", "find", "show", "buy",
}


def _singular(word: str) -> str:
    if len(word) <= 3 or word.endswith("ss"):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("sses", "xes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


class QueryKey:
    """Turns different wordings of the same search into one cache key.

    "Air Fryers", "air fryer deals" and "best black friday air fryer" all become "air-fryer".
    """

    PRICE = re.compile(r"\b(?:under|below|less than|max|up to)\s*\$?\s*(\d[\d,]*)")

    @classmethod
    def make(cls, query: str) -> str:
        text = query.lower().replace("’", "").replace("'", "")
        price = cls.PRICE.search(text)
        if price:
            text = text.replace(price.group(0), " ")
        words = [_singular(w) for w in re.findall(r"[a-z0-9]+", text) if w not in STOPWORDS]
        key_words = sorted(dict.fromkeys(words))
        if price:
            key_words.append("under" + price.group(1).replace(",", ""))
        return "-".join(key_words)[:120]

    @staticmethod
    def display(query: str) -> str:
        return " ".join(query.split())[:80]


@dataclass
class CachedResult:
    key: str
    query: str
    payload: dict
    cost: float
    created_at: float
    views: int

    @property
    def age_minutes(self) -> int:
        return int((time.time() - self.created_at) // 60)


class DealCache:
    """Search results kept for a few hours so friends reuse each other's searches for free."""

    def __init__(self, db: Database, ttl_hours: float):
        self._db = db
        self._ttl = ttl_hours * 3600

    def _fresh_cutoff(self) -> float:
        return time.time() - self._ttl

    @staticmethod
    def _row(row: sqlite3.Row) -> CachedResult:
        return CachedResult(
            key=row["key"], query=row["query"], payload=json.loads(row["payload"]),
            cost=row["cost"], created_at=row["created_at"], views=row["views"],
        )

    def get(self, key: str) -> CachedResult | None:
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT * FROM results WHERE key = ? AND created_at >= ?", (key, self._fresh_cutoff())
            ).fetchone()
            if row is None:
                return None
            self._db.conn.execute("UPDATE results SET views = views + 1 WHERE key = ?", (key,))
        return self._row(row)

    def put(self, key: str, query: str, payload: dict, cost: float) -> None:
        with self._db.lock:
            self._db.conn.execute(
                "INSERT INTO results (key, query, payload, cost, created_at, views) VALUES (?, ?, ?, ?, ?, 0) "
                "ON CONFLICT(key) DO UPDATE SET query=excluded.query, payload=excluded.payload, "
                "cost=excluded.cost, created_at=excluded.created_at, views=0",
                (key, query, json.dumps(payload), cost, time.time()),
            )

    def recent(self, limit: int = 24) -> list[CachedResult]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT * FROM results WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
                (self._fresh_cutoff(), limit),
            ).fetchall()
        return [self._row(r) for r in rows]
