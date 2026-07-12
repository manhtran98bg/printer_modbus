from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InsertPlcTriggerEventCommand:
    batch_id: str
    event_type: str
    register_address: int
    register_value: int
    created_at: int


@dataclass(frozen=True, slots=True)
class StartBatchSummaryCommand:
    batch_id: str
    started_at: int


@dataclass(frozen=True, slots=True)
class UpdateBatchSummaryCommand:
    batch_id: str
    success_count: int
    failed_count: int
    status: str
    updated_at: int
    ended_at: int = 0


DatabaseCommand = (
    InsertPlcTriggerEventCommand | StartBatchSummaryCommand | UpdateBatchSummaryCommand
)
