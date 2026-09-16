"""Historial de transcripciones en SQLite."""
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime

from neonwhisper.paths import HISTORY_DB


@dataclass
class Entry:
    id: int
    created_at: str
    text: str
    duration: float
    language: str


class History:
    def __init__(self, path=HISTORY_DB):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                text TEXT NOT NULL,
                duration REAL NOT NULL DEFAULT 0,
                language TEXT NOT NULL DEFAULT ''
            )"""
        )
        self._db.commit()

    def add(self, text: str, duration: float, language: str) -> Entry:
        created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO entries (created_at, text, duration, language) VALUES (?, ?, ?, ?)",
                (created, text, duration, language),
            )
            self._db.commit()
        return Entry(cur.lastrowid, created, text, duration, language)

    def list(self, query: str = "", limit: int = 500) -> list[Entry]:
        sql = "SELECT id, created_at, text, duration, language FROM entries"
        args: tuple = ()
        if query:
            sql += " WHERE text LIKE ?"
            args = (f"%{query}%",)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, args + (limit,)).fetchall()
        return [Entry(*r) for r in rows]

    def stats(self) -> tuple[int, int]:
        """(número de dictados, palabras totales)."""
        with self._lock:
            rows = self._db.execute("SELECT text FROM entries").fetchall()
        return len(rows), sum(len(r[0].split()) for r in rows)

    def delete(self, entry_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            self._db.commit()

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM entries")
            self._db.commit()
