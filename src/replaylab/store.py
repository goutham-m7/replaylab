"""JSON-only immutable traces and a content-addressed successful-result cache."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def canonical(value):
    def validate(item):
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise TypeError("JSON object keys must be strings")
            for child in item.values():
                validate(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                validate(child)

    validate(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def clone(value):
    return json.loads(canonical(value))


def request_key(request):
    return hashlib.sha256(canonical(request).encode()).hexdigest()


def now():
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str | Path):
        if str(path) == ":memory:":
            raise ValueError("Store requires a persistent SQLite file, not :memory:")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError(f"Unsupported trace schema {version}; expected 1")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, workflow TEXT NOT NULL, input TEXT NOT NULL,
                    mode TEXT NOT NULL, source TEXT REFERENCES runs(id), fork TEXT,
                    status TEXT NOT NULL, output TEXT, error TEXT,
                    created_at TEXT NOT NULL, finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS steps (
                    run_id TEXT NOT NULL REFERENCES runs(id), position INTEGER NOT NULL,
                    kind TEXT NOT NULL, name TEXT NOT NULL, key TEXT NOT NULL,
                    request TEXT NOT NULL, output TEXT, error TEXT,
                    state_before TEXT NOT NULL, state_after TEXT NOT NULL,
                    origin TEXT NOT NULL, duration_ms REAL NOT NULL,
                    PRIMARY KEY(run_id, position)
                );
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY, output TEXT NOT NULL, state_after TEXT NOT NULL
                );
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create_run(self, workflow, input, mode, source, fork):
        run_id = uuid4().hex
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, 'running', NULL, NULL, ?, NULL)",
                (run_id, workflow, canonical(input), mode, source, canonical(fork), now()),
            )
        return run_id

    def finish_run(self, run_id, status, output, error):
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET status=?, output=?, error=?, finished_at=? WHERE id=?",
                (status, canonical(output), canonical(error), now(), run_id),
            )

    @staticmethod
    def decode(row, fields):
        result = dict(row)
        for field in fields:
            if result[field] is not None:
                result[field] = json.loads(result[field])
        return result

    def get_run(self, run_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Run not found: {run_id}")
        return self.decode(row, ("input", "output", "error", "fork"))

    def list_runs(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY rowid DESC").fetchall()
        return [self.decode(row, ("input", "output", "error", "fork")) for row in rows]

    def steps(self, run_id):
        self.get_run(run_id)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM steps WHERE run_id=? ORDER BY position", (run_id,)
            ).fetchall()
        fields = ("request", "output", "error", "state_before", "state_after")
        return [self.decode(row, fields) for row in rows]

    def append_step(self, run_id, step):
        fields = ("request", "output", "error", "state_before", "state_after")
        row = {key: canonical(value) if key in fields else value for key, value in step.items()}
        row["run_id"] = run_id
        columns = ",".join(row)
        placeholders = ",".join("?" for _ in row)
        with self.connect() as conn:
            conn.execute(f"INSERT INTO steps ({columns}) VALUES ({placeholders})", tuple(row.values()))
            if step["error"] is None and step["origin"] == "executed":
                conn.execute(
                    "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
                    (step["key"], canonical(step["output"]), canonical(step["state_after"])),
                )

    def cached(self, key):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM cache WHERE key=?", (key,)).fetchone()
        return None if row is None else self.decode(row, ("output", "state_after"))
