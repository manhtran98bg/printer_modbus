from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ModbusPollEvent:
    sequence: int
    slave_id: int
    start_address: int
    registers: list[int]


@dataclass(frozen=True, slots=True)
class ModbusWriteEvent:
    sequence: int
    slave_id: int
    address: int
    values: list[int]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModbusErrorEvent:
    sequence: int
    message: str
    command: object


@dataclass(frozen=True, slots=True)
class ServerRequestCompletedEvent:
    request_type: str
    operation_id: str
    success: bool
    status_code: int = 0
    error: str = ""
    payload: dict[str, Any] | None = None

