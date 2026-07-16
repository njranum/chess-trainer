"""
chess.com public-API client (Design.md §7 stage 1).

Archive months are immutable once past (the gotcha in CLAUDE.md) and games
can only ever appear in the present — so there is nothing to cache and no
cache state to corrupt: a steady-state run fetches the current month (plus
the previous one for the rollover boundary), and historical months are
fetched only during an explicit --since backfill.
"""

from datetime import UTC, datetime

import requests

API_BASE = "https://api.chess.com/pub"
# chess.com asks for identifying contact in the UA; the profile is the contact.
USER_AGENT = "chess-trainer (personal training app; contact via chess.com profile)"


class ChesscomClient:
    def __init__(self, username: str, session: requests.Session | None = None):
        if not username:
            raise ValueError("CHESSCOM_USERNAME is not set")
        self.username = username.lower()
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def _get(self, url: str) -> dict:
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    def archive_months(self) -> list[tuple[int, int]]:
        """All (year, month) archive months for the user, oldest first."""
        data = self._get(f"{API_BASE}/player/{self.username}/games/archives")
        months = []
        for url in data.get("archives", []):
            year, month = url.rstrip("/").split("/")[-2:]
            months.append((int(year), int(month)))
        return sorted(months)

    def month_games(self, year: int, month: int) -> list[dict]:
        """Raw game dicts for one archive month."""
        data = self._get(f"{API_BASE}/player/{self.username}/games/{year}/{month:02d}")
        return data.get("games", [])

    def months_to_fetch(self, since: tuple[int, int] | None,
                        now: datetime | None = None) -> list[tuple[int, int]]:
        """Which months this run should fetch.

        Backfill (since given): every archive month from `since` onward.
        Steady state: current month + previous month (rollover boundary) —
        past months are immutable, so they are never re-fetched.
        """
        now = now or datetime.now(UTC)
        current = (now.year, now.month)
        previous = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        available = self.archive_months()
        if since is not None:
            return [m for m in available if m >= since]
        return [m for m in available if m in (current, previous)]
