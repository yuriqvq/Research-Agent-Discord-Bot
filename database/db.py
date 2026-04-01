"""
database/db.py — SQLite 資料庫管理模組
提供去重快取、頻道綁定、議題追蹤、Bot 狀態、執行紀錄的 CRUD 操作。
"""

import aiosqlite
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "research_agent.db"


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _create_tables(self) -> None:
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS dedup_cache (
                hash       TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS channel_bindings (
                category   TEXT PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                guild_id   INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tracked_topics (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                topic      TEXT NOT NULL UNIQUE,
                added_by   INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS execution_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger     TEXT NOT NULL,
                category    TEXT,
                started_at  TEXT NOT NULL,
                finished_at TEXT,
                status      TEXT DEFAULT 'running',
                report_path TEXT,
                error_msg   TEXT,
                new_count   INTEGER DEFAULT 0,
                dup_count   INTEGER DEFAULT 0
            );
        """)
        await self._db.commit()

    # --- 去重快取 ---

    async def is_duplicate(self, hash_val: str) -> bool:
        async with self._db.execute(
            "SELECT 1 FROM dedup_cache WHERE hash = ?", (hash_val,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def add_hash(self, hash_val: str, title: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT OR IGNORE INTO dedup_cache (hash, title, created_at) VALUES (?, ?, ?)",
            (hash_val, title, now),
        )
        await self._db.commit()

    async def add_hashes(self, items: list[tuple[str, str]]) -> None:
        """批次寫入多筆 hash。items: [(hash, title), ...]"""
        now = datetime.now(timezone.utc).isoformat()
        await self._db.executemany(
            "INSERT OR IGNORE INTO dedup_cache (hash, title, created_at) VALUES (?, ?, ?)",
            [(h, t, now) for h, t in items],
        )
        await self._db.commit()

    async def purge_expired(self, retention_days: int = 3) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        cursor = await self._db.execute(
            "DELETE FROM dedup_cache WHERE created_at < ?", (cutoff,)
        )
        await self._db.commit()
        return cursor.rowcount

    # --- 頻道綁定 ---

    async def get_channel_id(self, category: str) -> int | None:
        async with self._db.execute(
            "SELECT channel_id FROM channel_bindings WHERE category = ?", (category,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set_channel(self, category: str, channel_id: int, guild_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT INTO channel_bindings (category, channel_id, guild_id, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(category) DO UPDATE SET
                   channel_id = excluded.channel_id,
                   guild_id = excluded.guild_id,
                   updated_at = excluded.updated_at""",
            (category, channel_id, guild_id, now),
        )
        await self._db.commit()

    async def get_all_channels(self) -> dict[str, int]:
        """回傳 {category: channel_id}。"""
        async with self._db.execute(
            "SELECT category, channel_id FROM channel_bindings"
        ) as cursor:
            return {row[0]: row[1] async for row in cursor}

    # --- 議題追蹤 ---

    async def add_topic(self, topic: str, user_id: int) -> bool:
        """新增追蹤議題。回傳 True 若成功，False 若已存在。"""
        now = datetime.now(timezone.utc).isoformat()
        try:
            await self._db.execute(
                "INSERT INTO tracked_topics (topic, added_by, created_at) VALUES (?, ?, ?)",
                (topic, user_id, now),
            )
            await self._db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_topic(self, topic: str) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM tracked_topics WHERE topic = ?", (topic,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_all_topics(self) -> list[dict]:
        """回傳 [{id, topic, added_by, created_at}, ...]。"""
        async with self._db.execute(
            "SELECT id, topic, added_by, created_at FROM tracked_topics ORDER BY id"
        ) as cursor:
            return [
                {"id": r[0], "topic": r[1], "added_by": r[2], "created_at": r[3]}
                async for r in cursor
            ]

    # --- Bot 狀態 ---

    async def get_state(self, key: str) -> str | None:
        async with self._db.execute(
            "SELECT value FROM bot_state WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set_state(self, key: str, value: str) -> None:
        await self._db.execute(
            """INSERT INTO bot_state (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )
        await self._db.commit()

    # --- 執行紀錄 ---

    async def log_start(self, trigger: str, category: str | None = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            """INSERT INTO execution_log (trigger, category, started_at)
               VALUES (?, ?, ?)""",
            (trigger, category, now),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def log_finish(
        self,
        log_id: int,
        status: str,
        report_path: str | None = None,
        error_msg: str | None = None,
        new_count: int = 0,
        dup_count: int = 0,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """UPDATE execution_log
               SET finished_at = ?, status = ?, report_path = ?,
                   error_msg = ?, new_count = ?, dup_count = ?
               WHERE id = ?""",
            (now, status, report_path, error_msg, new_count, dup_count, log_id),
        )
        await self._db.commit()

    async def get_last_run(self) -> dict | None:
        async with self._db.execute(
            """SELECT id, trigger, category, started_at, finished_at,
                      status, report_path, new_count, dup_count
               FROM execution_log ORDER BY id DESC LIMIT 1"""
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "trigger": row[1],
                "category": row[2],
                "started_at": row[3],
                "finished_at": row[4],
                "status": row[5],
                "report_path": row[6],
                "new_count": row[7],
                "dup_count": row[8],
            }

    async def get_cache_stats(self) -> dict:
        """回傳去重快取統計。"""
        async with self._db.execute("SELECT COUNT(*) FROM dedup_cache") as cursor:
            row = await cursor.fetchone()
            return {"total": row[0]}
