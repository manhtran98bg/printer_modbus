from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from src.foundation.paths import SQLITE_PATH
from src.infrastructure.database.schema import SCHEMA_SQL


class SqliteDatabase:
    def __init__(self, db_path: str | Path = SQLITE_PATH) -> None:
        self._db_path = Path(db_path)
        self._connection: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    def open(self) -> None:
        if self._connection is not None:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self.initialize_schema()

    def initialize_schema(self) -> None:
        self.connection.executescript(SCHEMA_SQL)
        self.connection.commit()

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Database is not open")
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connection
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def close(self) -> None:
        if self._connection is None:
            return
        self._connection.close()
        self._connection = None
