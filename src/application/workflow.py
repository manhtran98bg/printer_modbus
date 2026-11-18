from __future__ import annotations

import logging
import re
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
    UpsertCommunicationEventCommand,
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
        self._pending_started_at: dict[str, int] = {}
        self._pending_box_counts: dict[str, int] = {}
        self._current_batch_id = ""
        self._plc_connected: bool | None = None

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
            return self._handle_modbus_write(event)

        if isinstance(event, ModbusErrorEvent):
            return self._handle_modbus_error(event)

        if isinstance(event, ServerRequestCompletedEvent):
            return self._handle_server_completed(event)

        return []

    def _handle_modbus_poll(self, event: ModbusPollEvent) -> list[WorkflowCommand]:
        self._slave_id = int(event.slave_id)
        values = self._poll_values(event)
        self._clear_inactive_server_requests(values)
        connection_commands = self._plc_connected_commands()

        if values.get(REGISTER_RESET_REQUEST, 0) == REQUEST_ACTIVE:
            self._last_values.update(values)
            return connection_commands + self._reset_flow_commands()

        commands: list[WorkflowCommand] = list(connection_commands)
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
            started_at = self._timestamp()
            box_count = int(values.get(REGISTER_BOX_COUNT, 0))
            self._pending_server_requests[request_type] = operation_id
            self._pending_started_at[request_type] = started_at
            self._pending_box_counts[request_type] = box_count
            response_register = SERVER_RESPONSE_REGISTERS[request_type]
            self._log_plc_event(f"D{request_register}={request_type}")

            if request_type == "end_batch":
                command: ServerCommand = EndBatchCommand(operation_id=operation_id)
            elif request_type == "start_batch":
                command = StartBatchCommand(
                    operation_id=operation_id,
                    box_count=box_count,
                )
            elif request_type == "print_next":
                command = PrintNextCommand(operation_id=operation_id)
            else:
                command = RePrintCommand(operation_id=operation_id)

            return [
                self._write(response_register, RESPONSE_PENDING),
                command,
                self._dashboard_event(
                    operation_id=operation_id,
                    action=request_type,
                    request_register=request_register,
                    response_register=response_register,
                    box_count=box_count if request_type == "start_batch" else 0,
                    status="processing",
                    message="Đang chờ MES phản hồi",
                    started_at=started_at,
                    updated_at=started_at,
                ),
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
        started_at = self._pending_started_at.get(event.request_type, now)
        box_count = self._pending_box_counts.get(event.request_type, 0)

        if response_value == RESPONSE_SUCCESS:
            if event.request_type == "start_batch":
                commands.extend(self._start_batch_commands(now, event))
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

        dashboard_status = self._dashboard_status(response_value)
        dashboard_message = self._dashboard_message(
            event,
            dashboard_status,
            box_count=box_count,
        )
        dashboard_event = self._dashboard_event(
            operation_id=event.operation_id,
            action=event.request_type,
            request_register=request_register,
            response_register=response_register,
            response_value=response_value,
            box_count=box_count if event.request_type == "start_batch" else 0,
            status=dashboard_status,
            http_status=int(event.status_code),
            message=dashboard_message,
            started_at=started_at,
            completed_at=now,
            updated_at=now,
        )
        commands.extend(
            [
                self._write(
                    response_register,
                    response_value,
                    metadata=self._dashboard_metadata(dashboard_event),
                ),
                self._reset(request_register),
            ]
        )
        return commands

    def _label_success_commands(self, now: int) -> list[WorkflowCommand]:
        if self._batch.active:
            self._batch.label_success_count += 1
        self._pending_attack = False
        self._log_plc_event("D2=label_success")
        operation_id = uuid.uuid4().hex
        pending_event = self._dashboard_event(
            operation_id=operation_id,
            action="label_success",
            request_register=REGISTER_LABEL_SUCCESS_REQUEST,
            response_register=REGISTER_LABEL_SUCCESS_RESPONSE,
            status="processing",
            message="Đang xác nhận tem đã in",
            started_at=now,
            updated_at=now,
        )
        completed_event = self._dashboard_event(
            operation_id=operation_id,
            action="label_success",
            request_register=REGISTER_LABEL_SUCCESS_REQUEST,
            response_register=REGISTER_LABEL_SUCCESS_RESPONSE,
            response_value=RESPONSE_SUCCESS,
            status="success",
            message="Đã xóa trạng thái chờ in nội bộ",
            started_at=now,
            completed_at=now,
            updated_at=now,
        )

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
                pending_event,
                self._write(
                    REGISTER_LABEL_SUCCESS_RESPONSE,
                    RESPONSE_SUCCESS,
                    metadata=self._dashboard_metadata(completed_event),
                ),
                self._reset(REGISTER_LABEL_SUCCESS_REQUEST),
            ]
        )
        return commands

    def _reset_flow_commands(self) -> list[WorkflowCommand]:
        self._pending_attack = False
        now = self._timestamp()
        cancelled_events = [
            self._dashboard_event(
                operation_id=operation_id,
                action=request_type,
                request_register=SERVER_REQUEST_REGISTERS[request_type],
                response_register=SERVER_RESPONSE_REGISTERS[request_type],
                box_count=self._pending_box_counts.get(request_type, 0),
                status="cancelled",
                message="Yêu cầu đã hủy do reset luồng in",
                started_at=self._pending_started_at.get(request_type, now),
                completed_at=now,
                updated_at=now,
            )
            for request_type, operation_id in self._pending_server_requests.items()
        ]
        self._pending_server_requests.clear()
        self._pending_started_at.clear()
        self._pending_box_counts.clear()
        self._log_plc_event("D5=reset")
        operation_id = uuid.uuid4().hex
        pending_event = self._dashboard_event(
            operation_id=operation_id,
            action="reset",
            request_register=REGISTER_RESET_REQUEST,
            response_register=REGISTER_RESET_RESPONSE,
            status="processing",
            message="Đang reset luồng in",
            started_at=now,
            updated_at=now,
        )
        completed_event = self._dashboard_event(
            operation_id=operation_id,
            action="reset",
            request_register=REGISTER_RESET_REQUEST,
            response_register=REGISTER_RESET_RESPONSE,
            response_value=RESPONSE_SUCCESS,
            status="success",
            message="Đã reset các biến nội bộ",
            started_at=now,
            completed_at=now,
            updated_at=now,
        )
        return cancelled_events + [
            pending_event,
            self._reset(REGISTER_START_BATCH_REQUEST),
            self._reset(REGISTER_PRINT_NEXT_REQUEST),
            self._reset(REGISTER_LABEL_SUCCESS_REQUEST),
            self._reset(REGISTER_REPRINT_REQUEST),
            self._write(
                REGISTER_RESET_RESPONSE,
                RESPONSE_SUCCESS,
                metadata=self._dashboard_metadata(completed_event),
            ),
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
                self._pending_started_at.pop(request_type, None)
                self._pending_box_counts.pop(request_type, None)

    def _attack_in_progress(self) -> bool:
        return (
            self._pending_attack
            or "print_next" in self._pending_server_requests
            or "reprint" in self._pending_server_requests
        )

    def _log_plc_event(self, event_name: str) -> None:
        logger.info("PLC event received: %s", event_name)

    def _start_batch_commands(
        self,
        now: int,
        event: ServerRequestCompletedEvent,
    ) -> list[WorkflowCommand]:
        metadata = self._mes_metadata(event)
        machine_id = self._batch_id_component(
            metadata.get("machine_id") if metadata else None
        )
        order_id = self._batch_id_component(
            metadata.get("order_id") if metadata else None
        )
        date_time = time.strftime("%Y%m%d%H%M%S", time.localtime(now))
        self._current_batch_id = f"{machine_id}_{order_id}_{date_time}"
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

    def _write(
        self,
        address: int,
        value: int,
        *,
        metadata: dict[str, object] | None = None,
    ) -> WriteRegistersCommand:
        return write_single_register(
            slave_id=self._slave_id,
            address=address,
            value=value,
            metadata=metadata,
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

    def _handle_modbus_write(self, event: ModbusWriteEvent) -> list[WorkflowCommand]:
        dashboard_data = event.metadata.get("dashboard_event")
        if not isinstance(dashboard_data, dict):
            return []
        now = self._timestamp()
        data = dict(dashboard_data)
        data["completed_at"] = now
        data["updated_at"] = now
        return [UpsertCommunicationEventCommand(**data)]

    def _handle_modbus_error(self, event: ModbusErrorEvent) -> list[WorkflowCommand]:
        now = self._timestamp()
        commands: list[WorkflowCommand] = []
        command = event.command
        if isinstance(command, WriteRegistersCommand):
            dashboard_data = command.metadata.get("dashboard_event")
            if isinstance(dashboard_data, dict):
                data = dict(dashboard_data)
                data["status"] = "error"
                data["message"] = (
                    f"Không thể ghi phản hồi D{command.address}: {event.message}"
                )
                data["completed_at"] = now
                data["updated_at"] = now
                commands.append(UpsertCommunicationEventCommand(**data))

        if self._plc_connected is not False:
            self._plc_connected = False
            commands.append(
                self._dashboard_event(
                    operation_id=uuid.uuid4().hex,
                    action="plc_connection",
                    direction="PLC ↔ APP",
                    status="error",
                    message=event.message or "Mất kết nối PLC",
                    started_at=now,
                    completed_at=now,
                    updated_at=now,
                )
            )
        return commands

    def _plc_connected_commands(self) -> list[WorkflowCommand]:
        if self._plc_connected is True:
            return []
        if self._plc_connected is None:
            self._plc_connected = True
            return []
        was_disconnected = self._plc_connected is False
        self._plc_connected = True
        now = self._timestamp()
        return [
            self._dashboard_event(
                operation_id=uuid.uuid4().hex,
                action="plc_connection",
                direction="PLC ↔ APP",
                status="success",
                message="PLC đã kết nối lại" if was_disconnected else "PLC đã kết nối",
                started_at=now,
                completed_at=now,
                updated_at=now,
            )
        ]

    def _dashboard_event(
        self,
        *,
        operation_id: str,
        action: str,
        status: str,
        message: str,
        started_at: int,
        updated_at: int,
        direction: str = "PLC → APP → MES → PLC",
        request_register: int = -1,
        request_value: int = REQUEST_ACTIVE,
        response_register: int = -1,
        response_value: int = RESPONSE_PENDING,
        box_count: int = 0,
        http_status: int = 0,
        completed_at: int = 0,
    ) -> UpsertCommunicationEventCommand:
        return UpsertCommunicationEventCommand(
            operation_id=operation_id,
            batch_id=self._current_batch_id,
            action=action,
            direction=direction,
            request_register=int(request_register),
            request_value=int(request_value),
            response_register=int(response_register),
            response_value=int(response_value),
            box_count=int(box_count),
            status=status,
            http_status=int(http_status),
            message=message,
            started_at=int(started_at),
            completed_at=int(completed_at),
            updated_at=int(updated_at),
        )

    @staticmethod
    def _dashboard_metadata(command: UpsertCommunicationEventCommand) -> dict[str, object]:
        return {
            "dashboard_event": {
                "operation_id": command.operation_id,
                "batch_id": command.batch_id,
                "action": command.action,
                "direction": command.direction,
                "request_register": command.request_register,
                "request_value": command.request_value,
                "response_register": command.response_register,
                "response_value": command.response_value,
                "box_count": command.box_count,
                "status": command.status,
                "http_status": command.http_status,
                "message": command.message,
                "started_at": command.started_at,
                "completed_at": command.completed_at,
                "updated_at": command.updated_at,
            }
        }

    @staticmethod
    def _dashboard_status(response_value: int) -> str:
        if response_value == RESPONSE_SUCCESS:
            return "success"
        if response_value == RESPONSE_REJECTED:
            return "rejected"
        return "error"

    @staticmethod
    def _dashboard_message(
        event: ServerRequestCompletedEvent,
        status: str,
        *,
        box_count: int,
    ) -> str:
        if (
            event.request_type == "start_batch"
            and int(event.status_code) == 404
            and PrinterWorkflow._server_error_message(event)
            == 'No print history with status "new" found'
        ):
            return "Lệnh in này đã được bắt đầu trước đó"
        if event.error:
            return event.error
        if event.request_type == "start_batch" and status == "success":
            metadata = PrinterWorkflow._mes_metadata(event)
            order_id = metadata.get("order_id") if metadata else None
            machine_id = metadata.get("machine_id") if metadata else None
            return (
                f"Order ID: {order_id or '—'} · "
                f"Machine ID: {machine_id or '—'} · "
                f"Box count: {int(box_count)}"
            )
        if status == "success":
            return "MES phản hồi thành công"
        if event.status_code:
            return f"MES phản hồi HTTP {event.status_code}"
        return "Timeout hoặc lỗi kết nối MES"

    @staticmethod
    def _server_error_message(event: ServerRequestCompletedEvent) -> str:
        if isinstance(event.payload, dict):
            for key in ("msg", "message"):
                message = event.payload.get(key)
                if message is not None:
                    return str(message)
        return str(event.error or "")

    @staticmethod
    def _mes_metadata(event: ServerRequestCompletedEvent) -> dict[str, object] | None:
        if not isinstance(event.payload, dict):
            return None
        metadata = event.payload.get("metaData")
        return metadata if isinstance(metadata, dict) else None

    @staticmethod
    def _batch_id_component(value: object) -> str:
        component = str(value or "").strip()
        component = re.sub(r"[^A-Za-z0-9.-]+", "-", component).strip("-.")
        return component or "UNKNOWN"

    @staticmethod
    def _timestamp() -> int:
        return int(time.time())
