from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PrintNextCommand:
    operation_id: str


@dataclass(frozen=True, slots=True)
class RePrintCommand:
    operation_id: str


@dataclass(frozen=True, slots=True)
class StartBatchCommand:
    operation_id: str
    box_count: int


@dataclass(frozen=True, slots=True)
class EndBatchCommand:
    operation_id: str


ServerCommand = PrintNextCommand | RePrintCommand | StartBatchCommand | EndBatchCommand
