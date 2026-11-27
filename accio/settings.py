"""Loads the site's settings: the API key from .env, friends and limits from friends.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent

MODEL = "claude-sonnet-5-5"
SECRET_FILE = Path("/etc/secrets/friends.toml")  # where Render mounts secret files


def load_dotenv(path: Path) -> None:
    """Reads KEY=value lines into the environment without overriding values already set."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Friend:
    name: str
    code: str
    daily_cap: float


@dataclass(frozen=True)
class Settings:
    friends: tuple[Friend, ...]
    daily_cap_site: float
    cache_hours: float
    timezone: ZoneInfo
    data_dir: Path
    model: str
    database_url: str | None = None

    @classmethod
    def load(cls, root: Path = ROOT) -> "Settings":
        load_dotenv(root / ".env")
        config = tomllib.loads(cls._friends_text(root))
        limits = config.get("limits", {})
        per_friend = float(limits.get("daily_cap_per_friend", 1.00))
        friends = tuple(
            Friend(
                name=str(entry["name"]),
                code=str(entry["code"]).strip(),
                daily_cap=float(entry.get("daily_cap", per_friend)),
            )
            for entry in config.get("friends", [])
            if entry.get("active", True)
        )
        codes = [f.code.lower() for f in friends]
        if len(codes) != len(set(codes)):
            raise SystemExit("Two friends in friends.toml share the same code. Give each a unique code.")

        data_dir = Path(os.environ.get("ACCIO_DATA", root / "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            friends=friends,
            daily_cap_site=float(limits.get("daily_cap_site", 5.00)),
            cache_hours=float(limits.get("cache_hours", 6)),
            timezone=ZoneInfo(str(limits.get("timezone", "America/Los_Angeles"))),
            data_dir=data_dir,
            model=os.environ.get("ACCIO_MODEL", MODEL),
            database_url=os.environ.get("DATABASE_URL") or None,
        )

    @staticmethod
    def _friends_text(root: Path) -> str:
        """friends.toml content: from ACCIO_FRIENDS_TOML, ACCIO_FRIENDS (a path),
        a Render secret file at /etc/secrets/friends.toml, or the project folder."""
        inline = os.environ.get("ACCIO_FRIENDS_TOML")
        if inline:
            return inline
        candidates = [os.environ.get("ACCIO_FRIENDS"), SECRET_FILE, root / "friends.toml"]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return Path(candidate).read_text()
        raise SystemExit(
            "Missing friends.toml. Copy friends.example.toml to friends.toml, "
            "then add friends with: python manage.py add-friend NAME"
        )
