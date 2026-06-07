from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.lock = threading.Lock()
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_mail (
                account TEXT NOT NULL,
                uid TEXT NOT NULL,
                message_id TEXT,
                pushed_at REAL NOT NULL,
                PRIMARY KEY (account, uid)
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_processed_message_id ON processed_mail(account, message_id)"
        )
        self.conn.commit()

    def is_processed(self, account: str, uid: str, message_id: Optional[str]) -> bool:
        with self.lock:
            if self.conn.execute(
                "SELECT 1 FROM processed_mail WHERE account = ? AND uid = ?",
                (account, uid),
            ).fetchone():
                return True
            if message_id:
                return (
                    self.conn.execute(
                        "SELECT 1 FROM processed_mail WHERE account = ? AND message_id = ?",
                        (account, message_id),
                    ).fetchone()
                    is not None
                )
            return False

    def mark_processed(self, account: str, uid: str, message_id: Optional[str]) -> None:
        with self.lock:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO processed_mail(account, uid, message_id, pushed_at)
                VALUES (?, ?, ?, ?)
                """,
                (account, uid, message_id, time.time()),
            )
            self.conn.commit()

    def close(self) -> None:
        with self.lock:
            self.conn.close()
