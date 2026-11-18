from __future__ import annotations

import json
from urllib.request import urlopen

from src.application.events import (
    ModbusErrorEvent,
    ModbusPollEvent,
    ServerRequestCompletedEvent,
)
from src.infrastructure.dashboard.service import DashboardService
from src.infrastructure.dashboard.state import DashboardState
from src.infrastructure.database.sqlite_database import SqliteDatabase
from src.models.settings import DashboardConfig


def test_dashboard_state_tracks_plc_mes_batch_and_registers():
    state = DashboardState()
    state.observe(
        ModbusPollEvent(
            sequence=1,
            slave_id=1,
            start_address=0,
            registers=[1, 0, 0, 0, 0, 0, 12] + [0] * 9,
        )
    )
    state.observe(
        ServerRequestCompletedEvent(
            request_type="start_batch",
            operation_id="op-1",
            success=False,
            status_code=422,
            error="Không có lệnh tem đang chờ",
        )
    )
    state.update_batch(
        batch_id="batch-1",
        active=True,
        success_count=3,
        failed_count=0,
    )

    snapshot = state.snapshot()

    assert snapshot["plc"]["status"] == "connected"
    assert snapshot["mes"]["status"] == "rejected"
    assert snapshot["mes"]["message"] == "Không có lệnh tem đang chờ"
    assert snapshot["batch"]["box_count"] == 12
    assert snapshot["batch"]["success_count"] == 3
    assert snapshot["registers"]["D0"] == 1

    state.observe(ModbusErrorEvent(sequence=2, message="PLC timeout", command=object()))
    assert state.snapshot()["plc"]["status"] == "disconnected"


def test_dashboard_serves_read_only_ui_and_api(tmp_path):
    db_path = tmp_path / "printer_modbus.db"
    database = SqliteDatabase(db_path)
    database.open()
    try:
        database.connection.execute(
            """
            INSERT INTO communication_event (
                operation_id, batch_id, action, direction,
                request_register, request_value, response_register, response_value,
                box_count, status, http_status, message,
                started_at, completed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "op-1",
                "batch-1",
                "start_batch",
                "PLC → APP → MES → PLC",
                0,
                1,
                10,
                2,
                10,
                "rejected",
                422,
                "Không có lệnh tem đang chờ",
                100,
                101,
                101,
            ),
        )
        database.connection.executemany(
            """
            INSERT INTO batch_label_summary (
                batch_id, started_at, ended_at, status,
                success_count, failed_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("batch-complete", 10, 20, "done", 2, 0, 10, 20),
                ("batch-no-print", 30, 40, "done", 0, 0, 30, 40),
                ("batch-active", 50, 0, "active", 1, 0, 50, 50),
            ],
        )
        database.connection.commit()
    finally:
        database.close()

    service = DashboardService(
        config=DashboardConfig(host="127.0.0.1", port=0),
        state=DashboardState(),
        db_path=db_path,
    )
    service.start()
    base_url = f"http://127.0.0.1:{service.bound_port}"
    try:
        with urlopen(f"{base_url}/", timeout=2) as response:
            page = response.read().decode("utf-8")
        with urlopen(f"{base_url}/nidec-logo.png", timeout=2) as response:
            logo_content_type = response.headers.get_content_type()
            logo = response.read()
        with urlopen(f"{base_url}/roboto-variable.ttf", timeout=2) as response:
            font_content_type = response.headers.get_content_type()
            font = response.read()
        with urlopen(f"{base_url}/api/dashboard?limit=10", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))

        assert "Giám sát máy in PLC - MES" in page
        assert 'src="/nidec-logo.png"' in page
        assert 'id="batch-pagination"' in page
        assert "const batchPageSize = 5" in page
        assert 'font-family: "Roboto"' in page
        assert "function hasActiveTextSelection()" in page
        assert "if (!hasActiveTextSelection())" in page
        assert "D6 = ${event.box_count ?? 0}" in page
        assert "const visibleRegisters = [0, 1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15]" in page
        assert logo_content_type == "image/png"
        assert logo == service._logo_path.read_bytes()
        assert font_content_type == "font/ttf"
        assert font == service._font_path.read_bytes()
        assert [batch["batch_id"] for batch in payload["batches"]] == [
            "batch-active",
            "batch-no-print",
            "batch-complete",
        ]
        assert payload["batches"][0]["status"] == "active"
        assert payload["batches"][1]["success_count"] == 0
        assert payload["events"][0]["operation_id"] == "op-1"
        assert payload["events"][0]["status"] == "rejected"
    finally:
        service.stop()
