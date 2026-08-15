import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA = """
CREATE TABLE IF NOT EXISTS api_tokens (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL,
 last_used_at TEXT,
 revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS download_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 token_id INTEGER NOT NULL REFERENCES api_tokens(id),
 created_at TEXT NOT NULL,
 success INTEGER NOT NULL CHECK(success IN (0, 1)),
 bytes_downloaded INTEGER NOT NULL DEFAULT 0,
 bytes_sent INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_created_token ON download_events(created_at, token_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=10000")
        return con

    async def run(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        def execute():
            with self._connect() as con:
                return fn(con)
        return await asyncio.to_thread(execute)

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        def init(con):
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.executescript(SCHEMA)
        await self.run(init)

    async def create_token(self, name: str, token_hash: str) -> dict:
        now = utc_now()
        def op(con):
            cur = con.execute(
                "INSERT INTO api_tokens(name,token_hash,created_at) VALUES(?,?,?)",
                (name, token_hash, now),
            )
            return {"id": cur.lastrowid, "name": name, "created_at": now}
        return await self.run(op)

    async def authenticate(self, token_hash: str) -> dict | None:
        now = utc_now()
        def op(con):
            row = con.execute(
                "SELECT id,name FROM api_tokens WHERE token_hash=? AND revoked_at IS NULL",
                (token_hash,),
            ).fetchone()
            if row:
                con.execute("UPDATE api_tokens SET last_used_at=? WHERE id=?", (now, row["id"]))
                return dict(row)
            return None
        return await self.run(op)

    async def list_tokens(self) -> list[dict]:
        return await self.run(lambda con: [dict(r) for r in con.execute(
            "SELECT id,name,created_at,last_used_at,revoked_at FROM api_tokens ORDER BY id"
        ).fetchall()])

    async def revoke_token(self, token_id: int) -> bool:
        def op(con):
            cur = con.execute(
                "UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (utc_now(), token_id),
            )
            return cur.rowcount == 1
        return await self.run(op)

    async def record_event(self, token_id: int, success: bool, downloaded: int = 0, sent: int = 0) -> None:
        await self.run(lambda con: con.execute(
            "INSERT INTO download_events(token_id,created_at,success,bytes_downloaded,bytes_sent) VALUES(?,?,?,?,?)",
            (token_id, utc_now(), int(success), downloaded, sent),
        ))

    async def stats(self, month: str) -> dict:
        prefix = month + "%"
        def op(con):
            rows = con.execute("""
              SELECT t.name,t.last_used_at,
                COALESCE(SUM(CASE WHEN e.success=1 THEN 1 ELSE 0 END),0) downloads,
                COALESCE(SUM(CASE WHEN e.success=0 THEN 1 ELSE 0 END),0) failed,
                COALESCE(SUM(e.bytes_downloaded),0) bytes_downloaded,
                COALESCE(SUM(e.bytes_sent),0) bytes_sent
              FROM api_tokens t LEFT JOIN download_events e
                ON e.token_id=t.id AND e.created_at LIKE ?
              GROUP BY t.id ORDER BY t.id
            """, (prefix,)).fetchall()
            users = [dict(r) for r in rows]
            return {
                "month": month,
                "total": {
                    "downloads": sum(r["downloads"] for r in users),
                    "failed": sum(r["failed"] for r in users),
                    "bytes_downloaded": sum(r["bytes_downloaded"] for r in users),
                    "bytes_sent": sum(r["bytes_sent"] for r in users),
                },
                "users": users,
            }
        return await self.run(op)
