from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any

from .tesla import LiveSample


class Storage:
    def __init__(self, path: str) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sampled_at TEXT NOT NULL,
                    energy_site_id INTEGER NOT NULL,
                    solar_kw REAL NOT NULL,
                    home_kw REAL NOT NULL,
                    grid_kw REAL NOT NULL,
                    battery_kw REAL NOT NULL,
                    battery_soc REAL NOT NULL
                );
                """
            )

    def save_tokens(self, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO oauth_tokens(singleton, payload, updated_at)
                   VALUES (1, ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET
                     payload=excluded.payload, updated_at=excluded.updated_at""",
                (json.dumps(payload), datetime.now(timezone.utc).isoformat()),
            )

    def load_tokens(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM oauth_tokens WHERE singleton = 1"
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def save_sample(self, energy_site_id: int, sample: LiveSample) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO samples(
                     sampled_at, energy_site_id, solar_kw, home_kw, grid_kw,
                     battery_kw, battery_soc
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    energy_site_id,
                    sample.solar_kw,
                    sample.home_kw,
                    sample.grid_kw,
                    sample.battery_kw,
                    sample.battery_soc,
                ),
            )

