import sqlite3
from pathlib import Path


class FeedbackStore:
    """Persist message feedback in a lightweight SQLite database."""

    def __init__(self):
        workspace_root = Path(__file__).parent.parent.parent.parent
        self.db_path = workspace_root / "database" / "feedback.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS message_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    value INTEGER NOT NULL CHECK(value IN (-1, 1)),
                    message_excerpt TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(session_id, message_id)
                )
                """
            )
            conn.commit()

    def save_feedback(
        self, session_id: str, message_id: str, value: int, message_excerpt: str = ""
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO message_feedback (session_id, message_id, value, message_excerpt)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, message_id)
                DO UPDATE SET
                    value = excluded.value,
                    message_excerpt = excluded.message_excerpt,
                    created_at = CURRENT_TIMESTAMP
                """,
                (session_id, message_id, value, message_excerpt[:500]),
            )
            conn.commit()
