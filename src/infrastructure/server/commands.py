from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PrintNextCommand:
    pass


@dataclass(frozen=True, slots=True)
class RePrintCommand:
    pass


@dataclass(frozen=True, slots=True)
class StartBatchCommand:
    pass


@dataclass(frozen=True, slots=True)
class EndBatchCommand:
    pass


ServerCommand = PrintNextCommand | RePrintCommand | StartBatchCommand | EndBatchCommand
