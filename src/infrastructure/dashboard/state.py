from __future__ import annotations

import threading
import time
from typing import Any

from src.application.events import (
    ModbusErrorEvent,
    ModbusPollEvent,
    ServerRequestCompletedEvent,
)


class DashboardState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = int(time.time())
        self._plc_status = "unknown"
        self._plc_last_seen = 0
        self._plc_message = "Chưa nhận dữ liệu từ PLC"
        self._mes_status = "unknown"
        self._mes_last_seen = 0
        self._mes_http_status = 0
        self._mes_message = "Chưa gửi yêu cầu đến MES"
        self._batch_id = ""
        self._batch_active = False
        self._success_count = 0
        self._failed_count = 0
        self._registers: dict[int, int] = {}

    def observe(self, event: object) -> None:
        now = int(time.time())
        with self._lock:
            if isinstance(event, ModbusPollEvent):
                self._plc_status = "connected"
                self._plc_last_seen = now
                self._plc_message = "PLC đang phản hồi"
                self._registers = {
                    int(event.start_address) + index: int(value)
                    for index, value in enumerate(event.registers)
                }
                return

            if isinstance(event, ModbusErrorEvent):
                self._plc_status = "disconnected"
                self._plc_last_seen = now
                self._plc_message = event.message or "Không thể giao tiếp với PLC"
                return

            if isinstance(event, ServerRequestCompletedEvent):
                self._mes_last_seen = now
                self._mes_http_status = int(event.status_code)
                self._mes_message = event.error or "MES phản hồi thành công"
                if event.success and 200 <= int(event.status_code) <= 299:
                    self._mes_status = "success"
                elif 400 <= int(event.status_code) <= 499:
                    self._mes_status = "rejected"
                else:
                    self._mes_status = "error"

    def update_batch(
        self,
        *,
        batch_id: str,
        active: bool,
        success_count: int,
        failed_count: int,
    ) -> None:
        with self._lock:
            self._batch_id = str(batch_id)
            self._batch_active = bool(active)
            self._success_count = int(success_count)
            self._failed_count = int(failed_count)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "app": {
                    "status": "running",
                    "started_at": self._started_at,
                    "message": "Ứng dụng đang chạy",
                },
                "plc": {
                    "status": self._plc_status,
                    "last_seen": self._plc_last_seen,
                    "message": self._plc_message,
                },
                "mes": {
                    "status": self._mes_status,
                    "last_seen": self._mes_last_seen,
                    "http_status": self._mes_http_status,
                    "message": self._mes_message,
                },
                "batch": {
                    "id": self._batch_id,
                    "active": self._batch_active,
                    "box_count": int(self._registers.get(6, 0)),
                    "success_count": self._success_count,
                    "failed_count": self._failed_count,
                },
                "registers": {
                    f"D{address}": value
                    for address, value in sorted(self._registers.items())
                    if 0 <= address <= 15
                },
            }
