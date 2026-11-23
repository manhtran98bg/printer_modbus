from __future__ import annotations

import logging
import queue

from src.application.agent import PrinterModbusAgent
from src.application.workflow import PrinterWorkflow
from src.foundation.logging import setup_logging
from src.infrastructure.database.service import DatabaseService
from src.infrastructure.dashboard.service import DashboardService
from src.infrastructure.dashboard.state import DashboardState
from src.infrastructure.modbus.service import ModbusService
from src.infrastructure.server.service import ServerService
from src.infrastructure.settings_repository import SettingsRepository


logger = logging.getLogger(__name__)


class ApplicationContainer:
    def __init__(self) -> None:
        setup_logging("INFO")
        self.settings_repository = SettingsRepository()
        self.settings = self.settings_repository.load()
        setup_logging(self.settings.service.log_level)
        self._log_config()

        self.event_queue: queue.Queue[object] = queue.Queue()
        self.workflow = PrinterWorkflow(
            use_d6_box_count=self.settings.server.use_d6_box_count,
        )
        self.dashboard_state = DashboardState()
        self.database_service = DatabaseService(
            communication_retention_days=self.settings.dashboard.retention_days,
        )
        self.modbus_service = ModbusService(
            config=self.settings.modbus,
            event_queue=self.event_queue,
        )
        self.server_service = ServerService(
            config=self.settings.server,
            event_queue=self.event_queue,
        )
        self.dashboard_service = DashboardService(
            config=self.settings.dashboard,
            state=self.dashboard_state,
            db_path=self.database_service.db_path,
        )
        self.agent = PrinterModbusAgent(
            event_queue=self.event_queue,
            workflow=self.workflow,
            modbus_service=self.modbus_service,
            server_service=self.server_service,
            database_service=self.database_service,
            dashboard_state=self.dashboard_state,
        )

    def start(self) -> None:
        logger.info("Starting printer_modbus")
        self.agent.start()
        self.dashboard_service.start()

    def run_forever(self) -> None:
        self.agent.run_forever()

    def request_shutdown(self) -> None:
        self.agent.request_shutdown()

    def shutdown(self) -> None:
        logger.info("Shutting down printer_modbus")
        self.dashboard_service.stop()
        self.agent.shutdown()

    def _log_config(self) -> None:
        modbus = self.settings.modbus
        server = self.settings.server
        logger.info(
            "Loaded device config device_id=%s device_name=%s",
            self.settings.device.device_id,
            self.settings.device.device_name,
        )
        logger.info(
            "Loaded modbus config enabled=%s type=%s slave_id=%s poll_interval_ms=%s "
            "timeout=%s retries=%s rtu_port=%s tcp=%s:%s",
            modbus.enabled,
            modbus.modbus_type,
            modbus.slave_id,
            modbus.poll_interval_ms,
            modbus.timeout,
            modbus.retries,
            modbus.rtu.port,
            modbus.tcp.host,
            modbus.tcp.port,
        )
        logger.info(
            "Loaded server config enabled=%s use_d6_box_count=%s base_url=%s "
            "start_batch_path=%s "
            "print_next_path=%s reprint_path=%s end_batch_path=%s timeout=%s "
            "retries=%s token_configured=%s",
            server.enabled,
            server.use_d6_box_count,
            server.base_url,
            server.start_batch_path,
            server.print_next_path,
            server.reprint_path,
            server.end_batch_path,
            server.timeout,
            server.retries,
            bool(server.token),
        )
        dashboard = self.settings.dashboard
        logger.info(
            "Loaded dashboard config enabled=%s host=%s port=%s refresh_ms=%s "
            "retention_days=%s",
            dashboard.enabled,
            dashboard.host,
            dashboard.port,
            dashboard.refresh_ms,
            dashboard.retention_days,
        )

