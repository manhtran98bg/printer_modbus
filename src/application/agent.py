from __future__ import annotations

import logging
import queue
import threading

from src.application.workflow import PrinterWorkflow
from src.infrastructure.database.commands import (
    InsertPlcTriggerEventCommand,
    StartBatchSummaryCommand,
    UpdateBatchSummaryCommand,
    UpsertCommunicationEventCommand,
)
from src.infrastructure.dashboard.state import DashboardState
from src.infrastructure.database.service import DatabaseService
from src.infrastructure.modbus.commands import WriteRegistersCommand
from src.infrastructure.modbus.service import ModbusService
from src.infrastructure.server.commands import (
    EndBatchCommand,
    PrintNextCommand,
    RePrintCommand,
    StartBatchCommand,
)
from src.infrastructure.server.service import ServerService


logger = logging.getLogger(__name__)


class PrinterModbusAgent:
    def __init__(
        self,
        *,
        event_queue: queue.Queue[object],
        workflow: PrinterWorkflow,
        modbus_service: ModbusService,
        server_service: ServerService,
        database_service: DatabaseService,
        dashboard_state: DashboardState,
    ) -> None:
        self._event_queue = event_queue
        self._workflow = workflow
        self._modbus_service = modbus_service
        self._server_service = server_service
        self._database_service = database_service
        self._dashboard_state = dashboard_state
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._stop_event.clear()
        self._database_service.start()
        self._modbus_service.start()
        self._server_service.start()
        logger.info("PrinterModbusAgent started")

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                event = self._event_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._dashboard_state.observe(event)
            commands = self._workflow.handle_event(event)
            batch = self._workflow.batch_counters
            self._dashboard_state.update_batch(
                batch_id=self._workflow.current_batch_id,
                active=batch.active,
                success_count=batch.label_success_count,
                failed_count=batch.label_failed_count,
            )
            for command in commands:
                self._route_command(command)

    def request_shutdown(self) -> None:
        self._stop_event.set()

    def shutdown(self) -> None:
        self._stop_event.set()
        self._server_service.stop()
        self._modbus_service.stop()
        self._database_service.stop(drain=True)
        logger.info("PrinterModbusAgent stopped")

    def _route_command(self, command: object) -> None:
        if isinstance(
            command,
            (
                InsertPlcTriggerEventCommand,
                StartBatchSummaryCommand,
                UpdateBatchSummaryCommand,
                UpsertCommunicationEventCommand,
            ),
        ):
            self._database_service.enqueue(command)
            return
        if isinstance(command, WriteRegistersCommand):
            self._modbus_service.enqueue_high_priority(command)
            return
        if isinstance(
            command,
            (PrintNextCommand, RePrintCommand, StartBatchCommand, EndBatchCommand),
        ):
            self._server_service.enqueue(command)
            return
        logger.debug("No command routing implemented for: %r", command)

