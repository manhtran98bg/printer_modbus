from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from pathlib import Path

from src.foundation.paths import SQLITE_PATH
from src.infrastructure.database.commands import (
    DatabaseCommand,
    InsertPlcTriggerEventCommand,
    StartBatchSummaryCommand,
    UpdateBatchSummaryCommand,
)
from src.infrastructure.database.queries import (
    INSERT_BATCH_SUMMARY,
    INSERT_PLC_TRIGGER_EVENT,
    UPDATE_BATCH_SUMMARY,
)
from src.infrastructure.database.sqlite_database import SqliteDatabase


logger = logging.getLogger(__name__)


class DatabaseService:
    def __init__(self, db_path: str | Path = SQLITE_PATH) -> None:
        self._database = SqliteDatabase(db_path)
        self._command_queue: queue.Queue[DatabaseCommand | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def db_path(self) -> Path:
        return self._database.db_path

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._database.open()
        self._thread = threading.Thread(
            target=self._run,
            name="database-worker",
            daemon=True,
        )
        self._thread.start()
        logger.info("Database service started db_path=%s", self._database.db_path)

    def stop(self, *, drain: bool = True) -> None:
        self._stop_event.set()
        if not drain:
            self._command_queue.put(None)
        if self._thread:
            self._thread.join(timeout=5)
        self._database.close()
        logger.info("Database service stopped")

    def enqueue(self, command: DatabaseCommand) -> None:
        self._command_queue.put(command)

    def _run(self) -> None:
        while not self._stop_event.is_set() or not self._command_queue.empty():
            try:
                command = self._command_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if command is None:
                return
            self._execute(command)

    def _execute(self, command: DatabaseCommand) -> None:
        try:
            now = int(time.time())
            with self._database.transaction() as connection:
                if isinstance(command, InsertPlcTriggerEventCommand):
                    connection.execute(
                        INSERT_PLC_TRIGGER_EVENT,
                        (
                            uuid.uuid4().hex,
                            command.batch_id,
                            command.event_type,
                            int(command.register_address),
                            int(command.register_value),
                            int(command.created_at or now),
                        ),
                    )
                    return

                if isinstance(command, StartBatchSummaryCommand):
                    timestamp = int(command.started_at or now)
                    connection.execute(
                        INSERT_BATCH_SUMMARY,
                        (command.batch_id, timestamp, "active", timestamp, timestamp),
                    )
                    return

                if isinstance(command, UpdateBatchSummaryCommand):
                    connection.execute(
                        UPDATE_BATCH_SUMMARY,
                        (
                            int(command.ended_at),
                            command.status,
                            int(command.success_count),
                            int(command.failed_count),
                            int(command.updated_at or now),
                            command.batch_id,
                        ),
                    )
                    return

            logger.warning("Unsupported database command: %r", command)
        except Exception:
            logger.exception("Database command failed: %r", command)
