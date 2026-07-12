from __future__ import annotations

import queue
import time

from src.infrastructure.modbus.commands import PollRegistersCommand, WriteRegistersCommand
from src.infrastructure.modbus.service import ModbusService
from src.models.settings import ModbusConfig


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.connected = False

    @property
    def is_connected(self) -> bool:
        return self.connected

    def connect(self, _config) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def read_holding_registers(self, slave_id: int, address: int, count: int) -> list[int]:
        self.calls.append(f"read:{slave_id}:{address}:{count}")
        return [0] * count

    def write_registers(self, slave_id: int, address: int, values: list[int]) -> None:
        self.calls.append(f"write:{slave_id}:{address}:{values}")


def test_modbus_service_prefers_high_priority_queue():
    event_queue: queue.Queue[object] = queue.Queue()
    client = FakeClient()
    service = ModbusService(
        config=ModbusConfig(enabled=False),
        event_queue=event_queue,
        client=client,
    )

    service.enqueue_normal_priority(PollRegistersCommand(slave_id=1, start_address=0, count=2))
    service.enqueue_high_priority(WriteRegistersCommand(slave_id=1, address=10, values=[7]))
    service.start()
    time.sleep(0.2)
    service.stop()

    assert client.calls[0] == "write:1:10:[7]"

