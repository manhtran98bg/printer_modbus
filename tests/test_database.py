from __future__ import annotations

import sqlite3

from src.infrastructure.database.commands import (
    InsertPlcTriggerEventCommand,
    StartBatchSummaryCommand,
    UpdateBatchSummaryCommand,
)
from src.infrastructure.database.service import DatabaseService
from src.infrastructure.database.sqlite_database import SqliteDatabase


def test_database_schema_creates_required_tables(tmp_path):
    db_path = tmp_path / "printer_modbus.db"
    database = SqliteDatabase(db_path)
    database.open()
    try:
        table_names = {
            row["name"]
            for row in database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        database.close()

    assert "plc_trigger_event" in table_names
    assert "batch_label_summary" in table_names


def test_database_service_writes_event_and_batch_summary(tmp_path):
    db_path = tmp_path / "printer_modbus.db"
    service = DatabaseService(db_path)
    service.start()
    service.enqueue(StartBatchSummaryCommand(batch_id="abc", started_at=100))
    service.enqueue(
        InsertPlcTriggerEventCommand(
            batch_id="abc",
            event_type="batch_started",
            register_address=0,
            register_value=1,
            created_at=100,
        )
    )
    service.enqueue(
        UpdateBatchSummaryCommand(
            batch_id="abc",
            success_count=2,
            failed_count=1,
            status="done",
            updated_at=200,
            ended_at=200,
        )
    )
    service.stop(drain=True)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        event = connection.execute("SELECT * FROM plc_trigger_event").fetchone()
        summary = connection.execute("SELECT * FROM batch_label_summary").fetchone()
    finally:
        connection.close()

    assert event["batch_id"] == "abc"
    assert event["event_type"] == "batch_started"
    assert summary["batch_id"] == "abc"
    assert summary["success_count"] == 2
    assert summary["failed_count"] == 1
    assert summary["status"] == "done"
