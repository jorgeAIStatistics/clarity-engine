"""Durable single-host state; remote graph writes are idempotent, not 2PC."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from .common import canonical, PipelineError


class State:
    def __init__(self, path):
        self.pg = path.startswith(("postgres://", "postgresql://"))
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row

            self.db = psycopg.connect(
                path, autocommit=True, row_factory=dict_row, connect_timeout=15
            )
        else:
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=WAL")
        self.execute(
            "CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(kind,id))"
        )
        self.execute(
            "CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY, owner TEXT, expires REAL)"
        )
        self.execute(
            "CREATE TABLE IF NOT EXISTS budgets(day TEXT PRIMARY KEY, calls INTEGER NOT NULL)"
        )

    def execute(self, query, parameters=()):
        if self.pg:
            import re

            # Namespace tables so the existing living-research service is isolated.
            for table in ("records", "leases", "budgets"):
                query = re.sub(r"\b" + table + r"\b", "clarity_pico_" + table, query)
            query = query.replace("?", "%s").replace(
                "expires REAL", "expires DOUBLE PRECISION"
            )
        return self.db.execute(query, parameters)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.execute("BEGIN" if self.pg else "BEGIN IMMEDIATE")
        try:
            yield
            self.execute("COMMIT")
        except BaseException:
            self.execute("ROLLBACK")
            raise

    def get(self, kind, id):
        row = self.execute(
            "SELECT body FROM records WHERE kind=? AND id=?", (kind, id)
        ).fetchone()
        return json.loads(row["body"]) if row else None

    def put(self, kind, id, value):
        self.execute(
            "INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
            (kind, id, canonical(value)),
        )

    def all(self, kind):
        return [
            json.loads(r["body"])
            for r in self.execute(
                "SELECT body FROM records WHERE kind=? ORDER BY id", (kind,)
            )
        ]

    def reserve_call(self, day, maximum):
        with self.transaction():
            self.execute(
                "INSERT INTO budgets VALUES(?,0) ON CONFLICT(day) DO NOTHING", (day,)
            )
            changed = self.execute(
                "UPDATE budgets SET calls=calls+1 WHERE day=? AND calls<?",
                (day, maximum),
            ).rowcount
            if not changed:
                raise PipelineError("daily_extraction_budget_exhausted")

    def acquire(self, id, owner, ttl=900):
        changed = self.execute(
            "INSERT INTO leases VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner, expires=excluded.expires WHERE leases.expires<?",
            (id, owner, time.time() + ttl, time.time()),
        ).rowcount
        if not changed:
            raise PipelineError("pipeline_already_running")

    def renew(self, id, owner, ttl=900):
        if not self.execute(
            "UPDATE leases SET expires=? WHERE id=? AND owner=? AND expires>?",
            (time.time() + ttl, id, owner, time.time()),
        ).rowcount:
            raise PipelineError("pipeline_lease_lost")

    def release(self, id, owner):
        self.execute("DELETE FROM leases WHERE id=? AND owner=?", (id, owner))
