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
    UpsertCommunicationEventCommand,
)
from src.infrastructure.database.queries import (
    DELETE_OLD_COMMUNICATION_EVENTS,
    INSERT_BATCH_SUMMARY,
    INSERT_PLC_TRIGGER_EVENT,
    UPDATE_BATCH_SUMMARY,
    UPSERT_COMMUNICATION_EVENT,
)
from src.infrastructure.database.sqlite_database import SqliteDatabase


logger = logging.getLogger(__name__)


class DatabaseService:
    def __init__(
        self,
        db_path: str | Path = SQLITE_PATH,
        *,
        communication_retention_days: int = 7,
    ) -> None:
        self._database = SqliteDatabase(db_path)
        self._communication_retention_seconds = max(
            1,
            int(communication_retention_days),
        ) * 86400
        self._last_cleanup_at = 0
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
        self._cleanup_old_communication_events(int(time.time()))
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

                if isinstance(command, UpsertCommunicationEventCommand):
                    connection.execute(
                        UPSERT_COMMUNICATION_EVENT,
                        (
                            command.operation_id,
                            command.batch_id,
                            command.action,
                            command.direction,
                            int(command.request_register),
                            int(command.request_value),
                            int(command.response_register),
                            int(command.response_value),
                            int(command.box_count),
                            command.status,
                            int(command.http_status),
                            command.message,
                            int(command.started_at),
                            int(command.completed_at),
                            int(command.updated_at),
                        ),
                    )
                    if now - self._last_cleanup_at >= 3600:
                        connection.execute(
                            DELETE_OLD_COMMUNICATION_EVENTS,
                            (now - self._communication_retention_seconds,),
                        )
                        self._last_cleanup_at = now
                    return

            logger.warning("Unsupported database command: %r", command)
        except Exception:
            logger.exception("Database command failed: %r", command)

    def _cleanup_old_communication_events(self, now: int) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                DELETE_OLD_COMMUNICATION_EVENTS,
                (int(now) - self._communication_retention_seconds,),
            )
        self._last_cleanup_at = int(now)
