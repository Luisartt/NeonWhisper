"""Las reuniones grabadas, en la misma base de datos que el historial de dictados."""
from __future__ import annotations  # `list` es un método de la clase: las anotaciones van diferidas

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime

from neonwhisper.paths import HISTORY_DB

# grabando -> transcribiendo -> resumiendo -> lista (o error en cualquier punto)
STATES = ("grabando", "transcribiendo", "resumiendo", "lista", "error")


@dataclass
class Meeting:
    id: int
    created_at: str
    app: str
    title: str
    duration: float
    audio_path: str
    transcript: str
    summary: str
    state: str
    error: str
    notes: str = ""     # lo que tú escribiste durante la reunión

    @property
    def label(self) -> str:
        return self.title.strip() or self.app or "Reunión"

    @property
    def words(self) -> int:
        return len(self.transcript.split())


_COLUMNS = "id, created_at, app, title, duration, audio_path, transcript, summary, state, error, notes"


class MeetingStore:
    def __init__(self, path=HISTORY_DB):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                app TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                duration REAL NOT NULL DEFAULT 0,
                audio_path TEXT NOT NULL DEFAULT '',
                transcript TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'grabando',
                error TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT ''
            )"""
        )
        # Bases de datos de versiones anteriores: se añade la columna que falte.
        existing = {row[1] for row in self._db.execute("PRAGMA table_info(meetings)")}
        if "notes" not in existing:
            self._db.execute("ALTER TABLE meetings ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        self._db.commit()

    def add(self, app: str, title: str, audio_path: str) -> Meeting:
        created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO meetings (created_at, app, title, audio_path, state) VALUES (?, ?, ?, ?, 'grabando')",
                (created, app, title, audio_path),
            )
            self._db.commit()
        return Meeting(cur.lastrowid, created, app, title, 0.0, audio_path, "", "", "grabando", "", "")

    def update(self, meeting_id: int, **fields) -> None:
        if not fields:
            return
        allowed = {"app", "title", "duration", "audio_path", "transcript", "summary", "state", "error", "notes"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE meetings SET {sets} WHERE id = ?", (*fields.values(), meeting_id))
            self._db.commit()

    def get(self, meeting_id: int) -> Meeting | None:
        with self._lock:
            row = self._db.execute(f"SELECT {_COLUMNS} FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        return Meeting(*row) if row else None

    def list(self, query: str = "", limit: int = 200) -> list[Meeting]:
        sql = f"SELECT {_COLUMNS} FROM meetings"
        args: tuple = ()
        if query:
            sql += " WHERE transcript LIKE ? OR summary LIKE ? OR title LIKE ? OR app LIKE ? OR notes LIKE ?"
            args = tuple([f"%{query}%"] * 5)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, args + (limit,)).fetchall()
        return [Meeting(*r) for r in rows]

    def unfinished(self) -> list[Meeting]:
        """Reuniones que quedaron a medias (p. ej. si se cortó la luz)."""
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_COLUMNS} FROM meetings WHERE state IN ('grabando', 'transcribiendo', 'resumiendo')"
            ).fetchall()
        return [Meeting(*r) for r in rows]

    def delete(self, meeting_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            self._db.commit()

    def stats(self) -> tuple[int, float]:
        """(reuniones grabadas, horas totales)."""
        with self._lock:
            row = self._db.execute("SELECT COUNT(*), COALESCE(SUM(duration), 0) FROM meetings").fetchone()
        return row[0], row[1] / 3600
