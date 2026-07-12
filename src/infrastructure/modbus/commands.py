from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PollRegistersCommand:
    slave_id: int
    start_address: int
    count: int
    reason: str = "poll"


@dataclass(frozen=True, slots=True)
class WriteRegistersCommand:
    slave_id: int
    address: int
    values: list[int]
    metadata: dict[str, Any] = field(default_factory=dict)


def write_single_register(
    *,
    slave_id: int,
    address: int,
    value: int,
    metadata: dict[str, Any] | None = None,
) -> WriteRegistersCommand:
    return WriteRegistersCommand(
        slave_id=int(slave_id),
        address=int(address),
        values=[int(value)],
        metadata=metadata or {},
    )


ModbusCommand = PollRegistersCommand | WriteRegistersCommand

