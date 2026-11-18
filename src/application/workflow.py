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
    REGISTER_BOX_COUNT,
    REGISTER_END_BATCH_REQUEST,
    REGISTER_END_BATCH_RESPONSE,
    REGISTER_LABEL_SUCCESS_REQUEST,
    REGISTER_LABEL_SUCCESS_RESPONSE,
    REGISTER_PRINT_NEXT_REQUEST,
    REGISTER_PRINT_NEXT_RESPONSE,
    REGISTER_REPRINT_REQUEST,
    REGISTER_REPRINT_RESPONSE,
    REGISTER_RESET_REQUEST,
    REGISTER_RESET_RESPONSE,
    REGISTER_START_BATCH_REQUEST,
    REGISTER_START_BATCH_RESPONSE,
    REQUEST_ACTIVE,
    RESPONSE_PENDING,
    RESPONSE_REJECTED,
    RESPONSE_SUCCESS,
    RESPONSE_TECHNICAL_ERROR,
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
    "start_batch": REGISTER_START_BATCH_REQUEST,
    "print_next": REGISTER_PRINT_NEXT_REQUEST,
    "reprint": REGISTER_REPRINT_REQUEST,
    "end_batch": REGISTER_END_BATCH_REQUEST,
}

SERVER_RESPONSE_REGISTERS = {
    "start_batch": REGISTER_START_BATCH_RESPONSE,
    "print_next": REGISTER_PRINT_NEXT_RESPONSE,
    "reprint": REGISTER_REPRINT_RESPONSE,
    "end_batch": REGISTER_END_BATCH_RESPONSE,
}

SERVER_REQUEST_PRIORITY = ("end_batch", "start_batch", "print_next", "reprint")


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
        self._pending_server_requests: dict[str, str] = {}
        self._current_batch_id = ""

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
        values = self._poll_values(event)
        self._clear_inactive_server_requests(values)

        if values.get(REGISTER_RESET_REQUEST, 0) == REQUEST_ACTIVE:
            self._last_values.update(values)
            return self._reset_flow_commands()

        commands: list[WorkflowCommand] = []
        label_success = values.get(REGISTER_LABEL_SUCCESS_REQUEST, 0)
        if self._changed_to(
            REGISTER_LABEL_SUCCESS_REQUEST,
            label_success,
            REQUEST_ACTIVE,
        ):
            commands.extend(self._label_success_commands(self._timestamp()))

        if not self._pending_server_requests:
            commands.extend(self._next_server_request(values))

        self._last_values.update(values)
        return commands

    def _next_server_request(self, values: dict[int, int]) -> list[WorkflowCommand]:
        for request_type in SERVER_REQUEST_PRIORITY:
            request_register = SERVER_REQUEST_REGISTERS[request_type]
            if values.get(request_register, 0) != REQUEST_ACTIVE:
                continue
            if request_type in {"print_next", "reprint"} and self._attack_in_progress():
                continue

            operation_id = uuid.uuid4().hex
            self._pending_server_requests[request_type] = operation_id
            response_register = SERVER_RESPONSE_REGISTERS[request_type]
            self._log_plc_event(f"D{request_register}={request_type}")

            if request_type == "end_batch":
                command: ServerCommand = EndBatchCommand(operation_id=operation_id)
            elif request_type == "start_batch":
                command = StartBatchCommand(
                    operation_id=operation_id,
                    box_count=int(values.get(REGISTER_BOX_COUNT, 0)),
                )
            elif request_type == "print_next":
                command = PrintNextCommand(operation_id=operation_id)
            else:
                command = RePrintCommand(operation_id=operation_id)

            return [
                self._write(response_register, RESPONSE_PENDING),
                command,
            ]
        return []

    def _handle_server_completed(
        self,
        event: ServerRequestCompletedEvent,
    ) -> list[WorkflowCommand]:
        pending_operation_id = self._pending_server_requests.get(event.request_type)
        if pending_operation_id != event.operation_id:
            logger.info(
                "Ignoring stale server completion request_type=%s operation_id=%s",
                event.request_type,
                event.operation_id,
            )
            return []

        request_register = SERVER_REQUEST_REGISTERS.get(event.request_type)
        response_register = SERVER_RESPONSE_REGISTERS.get(event.request_type)
        if request_register is None or response_register is None:
            return []

        response_value = self._response_value(event)
        commands: list[WorkflowCommand] = []
        now = self._timestamp()

        if response_value == RESPONSE_SUCCESS:
            if event.request_type == "start_batch":
                commands.extend(self._start_batch_commands(now))
            elif event.request_type == "print_next":
                self._pending_attack = True
                commands.append(
                    self._event_command(
                        "print_next_request",
                        REGISTER_PRINT_NEXT_REQUEST,
                        REQUEST_ACTIVE,
                        now,
                    )
                )
            elif event.request_type == "reprint":
                self._pending_attack = True
                commands.append(
                    self._event_command(
                        "reprint_request",
                        REGISTER_REPRINT_REQUEST,
                        REQUEST_ACTIVE,
                        now,
                    )
                )
            elif event.request_type == "end_batch":
                commands.extend(self._end_batch_commands(now))
        else:
            logger.warning(
                "Server request rejected or failed request_type=%s status=%s error=%s",
                event.request_type,
                event.status_code,
                event.error,
            )

        commands.extend(
            [
                self._write(response_register, response_value),
                self._reset(request_register),
            ]
        )
        return commands

    def _label_success_commands(self, now: int) -> list[WorkflowCommand]:
        if self._batch.active:
            self._batch.label_success_count += 1
        self._pending_attack = False
        self._log_plc_event("D2=label_success")

        commands: list[WorkflowCommand] = [
            self._event_command(
                "label_success",
                REGISTER_LABEL_SUCCESS_REQUEST,
                REQUEST_ACTIVE,
                now,
            )
        ]
        if self._batch.active and self._current_batch_id:
            commands.append(self._summary_command(status="active", updated_at=now))
        commands.extend(
            [
                self._write(REGISTER_LABEL_SUCCESS_RESPONSE, RESPONSE_SUCCESS),
                self._reset(REGISTER_LABEL_SUCCESS_REQUEST),
            ]
        )
        return commands

    def _reset_flow_commands(self) -> list[WorkflowCommand]:
        self._pending_attack = False
        self._pending_server_requests.clear()
        self._log_plc_event("D5=reset")
        return [
            self._reset(REGISTER_START_BATCH_REQUEST),
            self._reset(REGISTER_PRINT_NEXT_REQUEST),
            self._reset(REGISTER_LABEL_SUCCESS_REQUEST),
            self._reset(REGISTER_REPRINT_REQUEST),
            self._write(REGISTER_RESET_RESPONSE, RESPONSE_SUCCESS),
            self._reset(REGISTER_RESET_REQUEST),
        ]

    @staticmethod
    def _response_value(event: ServerRequestCompletedEvent) -> int:
        if event.success and 200 <= int(event.status_code) <= 299:
            return RESPONSE_SUCCESS
        if 400 <= int(event.status_code) <= 499:
            return RESPONSE_REJECTED
        return RESPONSE_TECHNICAL_ERROR

    @staticmethod
    def _poll_values(event: ModbusPollEvent) -> dict[int, int]:
        return {
            int(event.start_address) + index: int(value)
            for index, value in enumerate(event.registers)
        }

    def _changed_to(self, address: int, value: int, target: int) -> bool:
        return (
            int(value) == int(target)
            and self._last_values.get(address, 0) != int(target)
        )

    def _clear_inactive_server_requests(self, values: dict[int, int]) -> None:
        for request_type, address in SERVER_REQUEST_REGISTERS.items():
            if values.get(address, 0) != REQUEST_ACTIVE:
                self._pending_server_requests.pop(request_type, None)

    def _attack_in_progress(self) -> bool:
        return (
            self._pending_attack
            or "print_next" in self._pending_server_requests
            or "reprint" in self._pending_server_requests
        )

    def _log_plc_event(self, event_name: str) -> None:
        logger.info("PLC event received: %s", event_name)

    def _start_batch_commands(self, now: int) -> list[WorkflowCommand]:
        self._current_batch_id = uuid.uuid4().hex
        self._batch.active = True
        self._batch.label_success_count = 0
        self._batch.label_failed_count = 0
        self._pending_attack = False
        return [
            StartBatchSummaryCommand(
                batch_id=self._current_batch_id,
                started_at=now,
            ),
            self._event_command(
                "batch_started",
                REGISTER_START_BATCH_REQUEST,
                REQUEST_ACTIVE,
                now,
            ),
        ]

    def _end_batch_commands(self, now: int) -> list[WorkflowCommand]:
        self._batch.active = False
        self._pending_attack = False
        commands: list[WorkflowCommand] = [
            self._event_command(
                "batch_done",
                REGISTER_END_BATCH_REQUEST,
                REQUEST_ACTIVE,
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
        return commands

    def _write(self, address: int, value: int) -> WriteRegistersCommand:
        return write_single_register(
            slave_id=self._slave_id,
            address=address,
            value=value,
        )

    def _reset(self, address: int) -> WriteRegistersCommand:
        return self._write(address, 0)

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
