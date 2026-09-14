"""Durable single-host state; remote graph writes are idempotent, not 2PC."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from .common import canonical, PipelineError


class State:
    def __init__(self, path):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(kind,id))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY, owner TEXT, expires REAL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS budgets(day TEXT PRIMARY KEY, calls INTEGER NOT NULL)"
        )

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def get(self, kind, id):
        row = self.db.execute(
            "SELECT body FROM records WHERE kind=? AND id=?", (kind, id)
        ).fetchone()
        return json.loads(row["body"]) if row else None

    def put(self, kind, id, value):
        self.db.execute(
            "INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
            (kind, id, canonical(value)),
        )

    def all(self, kind):
        return [
            json.loads(r["body"])
            for r in self.db.execute(
                "SELECT body FROM records WHERE kind=? ORDER BY id", (kind,)
            )
        ]

    def reserve_call(self, day, maximum):
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO budgets VALUES(?,0)", (day,))
            changed = self.db.execute(
                "UPDATE budgets SET calls=calls+1 WHERE day=? AND calls<?",
                (day, maximum),
            ).rowcount
            if not changed:
                raise PipelineError("daily_extraction_budget_exhausted")

    def acquire(self, id, owner, ttl=900):
        changed = self.db.execute(
            "INSERT INTO leases VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner, expires=excluded.expires WHERE leases.expires<?",
            (id, owner, time.time() + ttl, time.time()),
        ).rowcount
        if not changed:
            raise PipelineError("pipeline_already_running")

    def renew(self, id, owner, ttl=900):
        if not self.db.execute(
            "UPDATE leases SET expires=? WHERE id=? AND owner=? AND expires>?",
            (time.time() + ttl, id, owner, time.time()),
        ).rowcount:
            raise PipelineError("pipeline_lease_lost")

    def release(self, id, owner):
        self.db.execute("DELETE FROM leases WHERE id=? AND owner=?", (id, owner))
