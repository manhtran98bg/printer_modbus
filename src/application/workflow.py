from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from src.application.events import (
    ModbusErrorEvent,
    ModbusPollEvent,
    ModbusWriteEvent,
    ServerRequestCompletedEvent,
)
from src.infrastructure.database.commands import (
    DatabaseCommand,
    InsertPlcTriggerEventCommand,
    StartBatchSummaryCommand,
    UpdateBatchSummaryCommand,
)
from src.infrastructure.modbus.commands import WriteRegistersCommand, write_single_register
from src.infrastructure.modbus.registers import (
    ACK_RECEIVED,
    ATTACK_BATCH_DONE,
    ATTACK_LABEL_FAILED,
    ATTACK_LABEL_SUCCESS,
    BATCH_STATE_ERROR,
    BATCH_STATE_NEW,
    REGISTER_ATTACK_BATCH_ACK,
    REGISTER_ATTACK_BATCH_DONE,
    REGISTER_ATTACK_LABEL_ACK,
    REGISTER_ATTACK_LABEL_STATE,
    REGISTER_BATCH_LABEL_COUNT,
    REGISTER_BATCH_STATE,
    REGISTER_BATCH_STATE_ACK,
    REGISTER_BATCH_SEQUENCE_ID,
    REGISTER_PENDING_RESET,
    REGISTER_PRINT_NEXT_ACK,
    REGISTER_PRINT_NEXT_REQUEST,
    REGISTER_RE_PRINT_ACK,
    REGISTER_RE_PRINT_REQUEST,
    REQUEST_ACTIVE,
)
from src.infrastructure.server.commands import (
    EndBatchCommand,
    PrintNextCommand,
    RePrintCommand,
    ServerCommand,
    StartBatchCommand,
)


logger = logging.getLogger(__name__)


WorkflowCommand = WriteRegistersCommand | ServerCommand | DatabaseCommand

SERVER_REQUEST_REGISTERS = {
    "start_batch": REGISTER_BATCH_STATE,
    "print_next": REGISTER_PRINT_NEXT_REQUEST,
    "reprint": REGISTER_RE_PRINT_REQUEST,
    "end_batch": REGISTER_ATTACK_BATCH_DONE,
}


@dataclass(slots=True)
class BatchCounters:
    active: bool = False
    label_success_count: int = 0
    label_failed_count: int = 0


class PrinterWorkflow:
    def __init__(self) -> None:
        self._last_values: dict[int, int] = {}
        self._batch = BatchCounters()
        self._slave_id = 1
        self._pending_attack = False
        self._pending_server_requests: set[str] = set()
        self._current_batch_id = ""
        self._batch_sequence_id = 0

    @property
    def batch_counters(self) -> BatchCounters:
        return self._batch

    @property
    def current_batch_id(self) -> str:
        return self._current_batch_id

    def handle_event(self, event: object) -> list[WorkflowCommand]:
        if isinstance(event, ModbusPollEvent):
            return self._handle_modbus_poll(event)

        if isinstance(event, ModbusWriteEvent):
            return []

        if isinstance(event, ModbusErrorEvent):
            return []

        if isinstance(event, ServerRequestCompletedEvent):
            return self._handle_server_completed(event)

        return []

    def _handle_modbus_poll(self, event: ModbusPollEvent) -> list[WorkflowCommand]:
        self._slave_id = int(event.slave_id)
        commands: list[WorkflowCommand] = []
        values = self._poll_values(event)
        self._clear_inactive_server_requests(values)

        batch_state = values.get(REGISTER_BATCH_STATE, 0)
        if self._changed_to(REGISTER_BATCH_STATE, batch_state, BATCH_STATE_NEW):
            if not self._server_request_pending("start_batch"):
                self._log_plc_event("D0=start_batch")
                self._pending_server_requests.add("start_batch")
                commands.append(StartBatchCommand())
        elif self._changed_to(REGISTER_BATCH_STATE, batch_state, BATCH_STATE_ERROR):
            now = self._timestamp()
            self._log_plc_event("D0=batch_error")
            commands.append(
                self._event_command(
                    "batch_error",
                    REGISTER_BATCH_STATE,
                    BATCH_STATE_ERROR,
                    now,
                )
            )
            if self._current_batch_id:
                commands.append(
                    self._summary_command(
                        status="error",
                        updated_at=now,
                    )
                )
            #commands.append(self._ack(REGISTER_BATCH_STATE_ACK, ACK_RECEIVED))
            #commands.append(self._reset(REGISTER_BATCH_STATE, 0))

        if self._changed_to(
            REGISTER_PRINT_NEXT_REQUEST,
            values.get(REGISTER_PRINT_NEXT_REQUEST, 0),
            REQUEST_ACTIVE,
        ) and not self._attack_in_progress():
            self._log_plc_event("D1=print_next")
            self._pending_server_requests.add("print_next")
            commands.append(PrintNextCommand())

        label_state = values.get(REGISTER_ATTACK_LABEL_STATE, 0)
        if self._changed_to(REGISTER_ATTACK_LABEL_STATE, label_state, ATTACK_LABEL_SUCCESS):
            now = self._timestamp()
            if self._batch.active:
                self._batch.label_success_count += 1
            self._log_plc_event("D2=label_success")

            commands.append(
                self._event_command(
                    "label_success",
                    REGISTER_ATTACK_LABEL_STATE,
                    ATTACK_LABEL_SUCCESS,
                    now,
                )
            )
            if self._batch.active and self._current_batch_id:
                commands.append(self._summary_command(status="active", updated_at=now))
            commands.append(self._ack(REGISTER_ATTACK_LABEL_ACK, ATTACK_LABEL_SUCCESS))
            commands.append(self._reset(REGISTER_ATTACK_LABEL_STATE, 0))
            self._pending_attack = False
        elif self._changed_to(REGISTER_ATTACK_LABEL_STATE, label_state, ATTACK_LABEL_FAILED):
            now = self._timestamp()
            if self._batch.active:
                self._batch.label_failed_count += 1
            self._log_plc_event("D2=label_failed")
            commands.append(
                self._event_command(
                    "label_failed",
                    REGISTER_ATTACK_LABEL_STATE,
                    ATTACK_LABEL_FAILED,
                    now,
                )
            )
            if self._batch.active and self._current_batch_id:
                commands.append(self._summary_command(status="active", updated_at=now))
            commands.append(self._ack(REGISTER_ATTACK_LABEL_ACK, ATTACK_LABEL_FAILED))
            commands.append(self._reset(REGISTER_ATTACK_LABEL_STATE, 0))
            self._pending_attack = False
        if self._changed_to(
            REGISTER_RE_PRINT_REQUEST,
            values.get(REGISTER_RE_PRINT_REQUEST, 0),
            REQUEST_ACTIVE,
        ) and not self._attack_in_progress():
            self._log_plc_event("D3=reprint")
            self._pending_server_requests.add("reprint")
            commands.append(RePrintCommand())

        if self._changed_to(
            REGISTER_ATTACK_BATCH_DONE,
            values.get(REGISTER_ATTACK_BATCH_DONE, 0),
            ATTACK_BATCH_DONE,
        ):
            if not self._server_request_pending("end_batch"):
                self._log_plc_event("D4=end_batch")
                self._pending_server_requests.add("end_batch")
                commands.append(EndBatchCommand())
                commands.extend(self._end_batch_commands(self._timestamp()))
                commands.append(self._reset(REGISTER_PENDING_RESET, 0))
                commands.append(self._reset(REGISTER_PRINT_NEXT_REQUEST, 0))
                commands.append(self._reset(REGISTER_ATTACK_LABEL_STATE, 0))
                commands.append(self._reset(REGISTER_RE_PRINT_REQUEST, 0))

        if self._changed_to(
            REGISTER_PENDING_RESET,
            values.get(REGISTER_PENDING_RESET, 0),
            REQUEST_ACTIVE,
        ):
            self._log_plc_event("D5=pending_reset")
            self._pending_attack = False
            commands.append(self._reset(REGISTER_PENDING_RESET, 0))
            commands.append(self._reset(REGISTER_BATCH_STATE, 0))
            commands.append(self._reset(REGISTER_PRINT_NEXT_REQUEST, 0))
            commands.append(self._reset(REGISTER_ATTACK_LABEL_STATE, 0))
            commands.append(self._reset(REGISTER_RE_PRINT_REQUEST, 0))
        for address, value in values.items():
            self._last_values[address] = value
        return commands

    def _handle_server_completed(
        self,
        event: ServerRequestCompletedEvent,
    ) -> list[WorkflowCommand]:
        if not event.success:
            self._pending_server_requests.discard(event.request_type)
            return []

        if event.request_type == "print_next":
            self._pending_attack = True
            now = self._timestamp()
            return [
                self._event_command(
                    "print_next_request",
                    REGISTER_PRINT_NEXT_REQUEST,
                    REQUEST_ACTIVE,
                    now,
                ),
                self._reset(REGISTER_PRINT_NEXT_REQUEST, 0),
                self._ack(REGISTER_PRINT_NEXT_ACK, ACK_RECEIVED),
            ]
        if event.request_type == "reprint":
            self._pending_attack = True
            now = self._timestamp()
            return [
                self._event_command(
                    "reprint_request",
                    REGISTER_RE_PRINT_REQUEST,
                    REQUEST_ACTIVE,
                    now,
                ),
                self._reset(REGISTER_RE_PRINT_REQUEST, 0),
                self._ack(REGISTER_RE_PRINT_ACK, ACK_RECEIVED),
            ]
        if event.request_type == "start_batch":
            label_count = self._start_batch_label_count(event.payload)
            if label_count is None:
                self._pending_server_requests.discard(event.request_type)
                return []
            sequence_id = self._next_batch_sequence_id()
            return [
                self._ack(REGISTER_BATCH_SEQUENCE_ID, sequence_id),
                self._ack(REGISTER_BATCH_LABEL_COUNT, label_count),
                *self._start_batch_commands(self._timestamp()),
                self._reset(REGISTER_BATCH_STATE, 0),
                self._ack(REGISTER_BATCH_STATE_ACK, ACK_RECEIVED),
            ]
        if event.request_type == "end_batch":
            return []
        return []

    def _poll_values(self, event: ModbusPollEvent) -> dict[int, int]:
        return {
            int(event.start_address) + index: int(value)
            for index, value in enumerate(event.registers)
        }

    def _changed_to(self, address: int, value: int, target: int) -> bool:
        #return int(value) == int(target) and self._last_values.get(address, 0) != int(target)
        return int(value) == int(target)

    def _clear_inactive_server_requests(self, values: dict[int, int]) -> None:
        for request_type, address in SERVER_REQUEST_REGISTERS.items():
            if values.get(address, 0) != REQUEST_ACTIVE:
                self._pending_server_requests.discard(request_type)

    def _server_request_pending(self, request_type: str) -> bool:
        return request_type in self._pending_server_requests

    def _attack_in_progress(self) -> bool:
        return (
            self._pending_attack
            or self._server_request_pending("print_next")
            or self._server_request_pending("reprint")
        )

    def _log_plc_event(self, event_name: str) -> None:
        logger.info("PLC event received: %s", event_name)

    def _start_batch_label_count(self, payload: dict[str, object] | None) -> int | None:
        if not isinstance(payload, dict):
            return None
        metadata = payload.get("metaData")
        if not isinstance(metadata, dict):
            return None
        value = metadata.get("label_counting")
        if isinstance(value, bool):
            return None
        try:
            label_count = int(value)
        except (TypeError, ValueError):
            return None
        if label_count < 0:
            return None
        return label_count

    def _next_batch_sequence_id(self) -> int:
        self._batch_sequence_id += 1
        if self._batch_sequence_id > 65535:
            self._batch_sequence_id = 1
        return self._batch_sequence_id

    def _start_batch_commands(self, now: int) -> list[WorkflowCommand]:
        self._current_batch_id = uuid.uuid4().hex
        self._batch.active = True
        self._batch.label_success_count = 0
        self._batch.label_failed_count = 0
        return [
            StartBatchSummaryCommand(
                batch_id=self._current_batch_id,
                started_at=now,
            ),
            self._event_command(
                "batch_started",
                REGISTER_BATCH_STATE,
                BATCH_STATE_NEW,
                now,
            )
        ]

    def _end_batch_commands(self, now: int) -> list[WorkflowCommand]:
        self._batch.active = False
        commands: list[WorkflowCommand] = [
            self._event_command(
                "batch_done",
                REGISTER_ATTACK_BATCH_DONE,
                ATTACK_BATCH_DONE,
                now,
            )
        ]
        if self._current_batch_id:
            commands.append(
                self._summary_command(
                    status="done",
                    updated_at=now,
                    ended_at=now,
                )
            )
        commands.extend(
            [
                self._reset(REGISTER_ATTACK_BATCH_DONE, 0),
                self._ack(REGISTER_ATTACK_BATCH_ACK, ACK_RECEIVED),
            ]
        )
        return commands

    def _ack(self, address: int, value: int) -> WriteRegistersCommand:
        return write_single_register(
            slave_id=self._slave_id,
            address=address,
            value=value,
        )
    def _reset(self, address: int, value: int) -> WriteRegistersCommand:
        return write_single_register(
            slave_id=self._slave_id,
            address=address,
            value=value,
        )
    def _event_command(
        self,
        event_type: str,
        register_address: int,
        register_value: int,
        created_at: int,
    ) -> InsertPlcTriggerEventCommand:
        return InsertPlcTriggerEventCommand(
            batch_id=self._current_batch_id,
            event_type=event_type,
            register_address=register_address,
            register_value=register_value,
            created_at=created_at,
        )

    def _summary_command(
        self,
        *,
        status: str,
        updated_at: int,
        ended_at: int = 0,
    ) -> UpdateBatchSummaryCommand:
        return UpdateBatchSummaryCommand(
            batch_id=self._current_batch_id,
            success_count=self._batch.label_success_count,
            failed_count=self._batch.label_failed_count,
            status=status,
            updated_at=updated_at,
            ended_at=ended_at,
        )

    @staticmethod
    def _timestamp() -> int:
        return int(time.time())
