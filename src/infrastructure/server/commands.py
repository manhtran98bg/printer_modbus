from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PrintNextCommand:
    pass


@dataclass(frozen=True, slots=True)
class RePrintCommand:
    pass


ServerCommand = PrintNextCommand | RePrintCommand
