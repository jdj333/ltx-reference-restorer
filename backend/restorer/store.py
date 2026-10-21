from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """Short transactions; durable JSON snapshots simplify provenance inspection."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "restorer.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, project_id TEXT,
                    created_at TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS records_kind_project ON records(kind, project_id);
                CREATE TABLE IF NOT EXISTS worker_lease (
                    id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT, heartbeat REAL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, kind: str, body: dict, project_id: str | None = None) -> dict:
        record = {**body, "id": uuid.uuid4().hex, "created_at": now()}
        if project_id:
            record["project_id"] = project_id
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if kind == "job":
                previous = db.execute("SELECT body FROM records WHERE kind='job' AND project_id=?", (project_id,)).fetchall()
                record["version"] = 1 + sum(json.loads(row[0])["shot_id"] == record["shot_id"] for row in previous)
            db.execute("INSERT INTO records VALUES(?,?,?,?,?)", (record["id"], kind, project_id, record["created_at"], json.dumps(record)))
        return record

    def get(self, kind: str, identity: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT body FROM records WHERE id=? AND kind=?", (identity, kind)).fetchone()
        if not row:
            raise KeyError(f"{kind} not found: {identity}")
        return json.loads(row[0])

    def list(self, kind: str, project_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            query = "SELECT body FROM records WHERE kind=?"
            args = [kind]
            if project_id:
                query += " AND project_id=?"
                args.append(project_id)
            rows = db.execute(query + " ORDER BY created_at,id", args).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update(self, kind: str, identity: str, changes: dict) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM records WHERE id=? AND kind=?", (identity, kind)).fetchone()
            if not row:
                raise KeyError(f"{kind} not found: {identity}")
            body = {**json.loads(row[0]), **changes, "id": identity}
            db.execute("UPDATE records SET body=? WHERE id=?", (json.dumps(body), identity))
        return body

    def claim_job(self) -> dict | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,body FROM records WHERE kind='job' ORDER BY created_at,id").fetchall()
            for row in rows:
                job = json.loads(row["body"])
                if job["state"] == "queued":
                    job.update(state="running", started_at=now(), progress=0, progress_stage="preparing_source")
                    db.execute("UPDATE records SET body=? WHERE id=?", (json.dumps(job), row["id"]))
                    return job
        return None
