from __future__ import annotations

import logging
from dataclasses import dataclass

from src.application.events import (
    ModbusErrorEvent,
    ModbusPollEvent,
    ModbusWriteEvent,
    ServerRequestCompletedEvent,
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
    REGISTER_BATCH_STATE,
    REGISTER_BATCH_STATE_ACK,
    REGISTER_PRINT_NEXT_ACK,
    REGISTER_PRINT_NEXT_REQUEST,
    REGISTER_RE_PRINT_ACK,
    REGISTER_RE_PRINT_REQUEST,
    REQUEST_ACTIVE,
)
from src.infrastructure.server.commands import PrintNextCommand, RePrintCommand, ServerCommand


logger = logging.getLogger(__name__)


WorkflowCommand = WriteRegistersCommand | ServerCommand


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

    @property
    def batch_counters(self) -> BatchCounters:
        return self._batch

    def handle_event(self, event: object) -> list[WorkflowCommand]:
        if isinstance(event, ModbusPollEvent):
            return self._handle_modbus_poll(event)

        if isinstance(event, ModbusWriteEvent):
            logger.debug(
                "Modbus write completed sequence=%s slave_id=%s address=%s values=%s",
                event.sequence,
                event.slave_id,
                event.address,
                event.values,
            )
            return []

        if isinstance(event, ModbusErrorEvent):
            logger.warning("Modbus error sequence=%s message=%s", event.sequence, event.message)
            return []

        if isinstance(event, ServerRequestCompletedEvent):
            return self._handle_server_completed(event)

        logger.debug("Ignored event: %r", event)
        return []

    def _handle_modbus_poll(self, event: ModbusPollEvent) -> list[WorkflowCommand]:
        self._slave_id = int(event.slave_id)
        commands: list[WorkflowCommand] = []
        values = self._poll_values(event)

        batch_state = values.get(REGISTER_BATCH_STATE, 0)
        if self._changed_to(REGISTER_BATCH_STATE, batch_state, BATCH_STATE_NEW):
            self._batch.active = True
            self._batch.label_success_count = 0
            self._batch.label_failed_count = 0
            logger.info("Batch started: counters reset")
            commands.append(self._ack(REGISTER_BATCH_STATE_ACK, ACK_RECEIVED, "batch_state_new"))
        elif self._changed_to(REGISTER_BATCH_STATE, batch_state, BATCH_STATE_ERROR):
            logger.warning("Batch state error received from PLC")
            commands.append(self._ack(REGISTER_BATCH_STATE_ACK, ACK_RECEIVED, "batch_state_error"))

        if self._changed_to(
            REGISTER_PRINT_NEXT_REQUEST,
            values.get(REGISTER_PRINT_NEXT_REQUEST, 0),
            REQUEST_ACTIVE,
        ):
            logger.info("PRINT_NEXT_REQUEST received from PLC")
            commands.append(PrintNextCommand())

        label_state = values.get(REGISTER_ATTACK_LABEL_STATE, 0)
        if self._changed_to(REGISTER_ATTACK_LABEL_STATE, label_state, ATTACK_LABEL_SUCCESS):
            if self._batch.active:
                self._batch.label_success_count += 1
            logger.info(
                "ATTACK_LABEL_STATE success received success_count=%s failed_count=%s",
                self._batch.label_success_count,
                self._batch.label_failed_count,
            )
            commands.append(
                self._ack(REGISTER_ATTACK_LABEL_ACK, ATTACK_LABEL_SUCCESS, "label_success")
            )
        elif self._changed_to(REGISTER_ATTACK_LABEL_STATE, label_state, ATTACK_LABEL_FAILED):
            if self._batch.active:
                self._batch.label_failed_count += 1
            logger.info(
                "ATTACK_LABEL_STATE failed received success_count=%s failed_count=%s",
                self._batch.label_success_count,
                self._batch.label_failed_count,
            )
            commands.append(
                self._ack(REGISTER_ATTACK_LABEL_ACK, ATTACK_LABEL_FAILED, "label_failed")
            )

        if self._changed_to(
            REGISTER_RE_PRINT_REQUEST,
            values.get(REGISTER_RE_PRINT_REQUEST, 0),
            REQUEST_ACTIVE,
        ):
            logger.info("RE_PRINT_REQUEST received from PLC")
            commands.append(RePrintCommand())

        if self._changed_to(
            REGISTER_ATTACK_BATCH_DONE,
            values.get(REGISTER_ATTACK_BATCH_DONE, 0),
            ATTACK_BATCH_DONE,
        ):
            self._batch.active = False
            logger.info(
                "Batch done received success_count=%s failed_count=%s",
                self._batch.label_success_count,
                self._batch.label_failed_count,
            )
            commands.append(self._ack(REGISTER_ATTACK_BATCH_ACK, ACK_RECEIVED, "batch_done"))

        for address, value in values.items():
            self._last_values[address] = value
        return commands

    def _handle_server_completed(
        self,
        event: ServerRequestCompletedEvent,
    ) -> list[WorkflowCommand]:
        if not event.success:
            logger.warning(
                "Server %s failed; PLC ACK withheld status=%s error=%s",
                event.request_type,
                event.status_code,
                event.error,
            )
            return []

        if event.request_type == "print_next":
            logger.info("Server print_next OK; ACK PLC register %s=1", REGISTER_PRINT_NEXT_ACK)
            return [self._ack(REGISTER_PRINT_NEXT_ACK, ACK_RECEIVED, "print_next_ok")]
        if event.request_type == "reprint":
            logger.info("Server reprint OK; ACK PLC register %s=1", REGISTER_RE_PRINT_ACK)
            return [self._ack(REGISTER_RE_PRINT_ACK, ACK_RECEIVED, "reprint_ok")]
        return []

    def _poll_values(self, event: ModbusPollEvent) -> dict[int, int]:
        return {
            int(event.start_address) + index: int(value)
            for index, value in enumerate(event.registers)
        }

    def _changed_to(self, address: int, value: int, target: int) -> bool:
        return int(value) == int(target) and self._last_values.get(address, 0) != int(target)

    def _ack(self, address: int, value: int, reason: str) -> WriteRegistersCommand:
        logger.info("Queue PLC ACK address=%s value=%s reason=%s", address, value, reason)
        return write_single_register(
            slave_id=self._slave_id,
            address=address,
            value=value,
            metadata={"reason": reason},
        )
