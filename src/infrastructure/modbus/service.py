from __future__ import annotations

import logging
import queue
import threading
import time
from itertools import count

from src.application.events import ModbusErrorEvent, ModbusPollEvent, ModbusWriteEvent
from src.infrastructure.modbus.client import (
    ModbusClientProtocol,
    ModbusRTUClient,
    ModbusRTUConfig,
    ModbusTCPClient,
    ModbusTCPConfig,
)
from src.infrastructure.modbus.commands import (
    ModbusCommand,
    PollRegistersCommand,
    WriteRegistersCommand,
)
from src.infrastructure.modbus.registers import POLL_REGISTER_COUNT, POLL_START_ADDRESS
from src.models.settings import ModbusConfig


logger = logging.getLogger(__name__)


class ModbusService:
    def __init__(
        self,
        config: ModbusConfig,
        event_queue: queue.Queue[object],
        client: ModbusClientProtocol | None = None,
    ) -> None:
        self._config = config
        self._event_queue = event_queue
        self._client = client
        self._high_priority_queue: queue.Queue[ModbusCommand] = queue.Queue()
        self._normal_priority_queue: queue.Queue[ModbusCommand] = queue.Queue()
        self._stop_event = threading.Event()
        self._wakeup_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._sequence = count(1)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="modbus-worker",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Modbus service started enabled=%s type=%s slave_id=%s poll_start=%s "
            "poll_count=%s poll_interval_ms=%s",
            self._config.enabled,
            self._config.modbus_type,
            self._config.slave_id,
            POLL_START_ADDRESS,
            POLL_REGISTER_COUNT,
            self._config.poll_interval_ms,
        )

    def stop(self) -> None:
        self._stop_event.set()
        self._wakeup_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._disconnect_client()
        logger.info("Modbus service stopped")

    def enqueue_high_priority(self, command: ModbusCommand) -> None:
        self._high_priority_queue.put(command)
        self._wakeup_event.set()

    def enqueue_normal_priority(self, command: ModbusCommand) -> None:
        self._normal_priority_queue.put(command)
        self._wakeup_event.set()

    def write_registers(
        self,
        address: int,
        values: list[int],
        *,
        slave_id: int | None = None,
    ) -> None:
        self.enqueue_high_priority(
            WriteRegistersCommand(
                slave_id=int(slave_id or self._config.slave_id),
                address=int(address),
                values=[int(value) for value in values],
            )
        )

    def _run(self) -> None:
        next_poll_at = time.monotonic()
        while not self._stop_event.is_set():
            now = time.monotonic()
            if self._config.enabled and now >= next_poll_at:
                self.enqueue_normal_priority(
                    PollRegistersCommand(
                        slave_id=self._config.slave_id,
                        start_address=POLL_START_ADDRESS,
                        count=POLL_REGISTER_COUNT,
                    )
                )
                next_poll_at = now + (self._config.poll_interval_ms / 1000)

            command = self._next_command()
            if command is not None:
                self._execute_command(command)
                continue

            timeout = max(0.05, min(0.5, next_poll_at - time.monotonic()))
            self._wakeup_event.wait(timeout)
            self._wakeup_event.clear()

    def _next_command(self) -> ModbusCommand | None:
        try:
            return self._high_priority_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            return self._normal_priority_queue.get_nowait()
        except queue.Empty:
            return None

    def _execute_command(self, command: ModbusCommand) -> None:
        sequence = next(self._sequence)
        try:
            client = self._ensure_client()
            if isinstance(command, PollRegistersCommand):
                logger.debug(
                    "Modbus poll start slave_id=%s address=%s count=%s reason=%s",
                    command.slave_id,
                    command.start_address,
                    command.count,
                    command.reason,
                )
                registers = client.read_holding_registers(
                    command.slave_id,
                    command.start_address,
                    command.count,
                )
                self._event_queue.put(
                    ModbusPollEvent(
                        sequence=sequence,
                        slave_id=command.slave_id,
                        start_address=command.start_address,
                        registers=registers,
                    )
                )
                return

            if isinstance(command, WriteRegistersCommand):
                logger.info(
                    "Modbus write slave_id=%s address=%s values=%s metadata=%s",
                    command.slave_id,
                    command.address,
                    command.values,
                    command.metadata,
                )
                client.write_registers(command.slave_id, command.address, command.values)
                self._event_queue.put(
                    ModbusWriteEvent(
                        sequence=sequence,
                        slave_id=command.slave_id,
                        address=command.address,
                        values=command.values,
                        metadata=command.metadata,
                    )
                )
                return
        except Exception as exc:
            logger.warning("Modbus command failed: %s", exc)
            self._disconnect_client()
            self._event_queue.put(
                ModbusErrorEvent(
                    sequence=sequence,
                    message=str(exc),
                    command=command,
                )
            )

    def _ensure_client(self) -> ModbusClientProtocol:
        if self._client and self._client.is_connected:
            return self._client

        if self._client is None:
            self._client = self._create_client()
        client_config = self._build_client_config()
        logger.info("Connecting Modbus type=%s config=%s", self._config.modbus_type, client_config)
        self._client.connect(client_config)
        return self._client

    def _create_client(self) -> ModbusClientProtocol:
        if self._config.modbus_type == "tcp":
            return ModbusTCPClient()
        return ModbusRTUClient()

    def _build_client_config(self) -> ModbusRTUConfig | ModbusTCPConfig:
        if self._config.modbus_type == "tcp":
            return ModbusTCPConfig(
                host=self._config.tcp.host,
                port=self._config.tcp.port,
                timeout=self._config.timeout,
                retries=self._config.retries,
            )
        return ModbusRTUConfig(
            port=self._config.rtu.port,
            baud_rate=self._config.rtu.baud_rate,
            data_bits=self._config.rtu.data_bits,
            parity=self._config.rtu.parity,
            stop_bits=self._config.rtu.stop_bits,
            timeout=self._config.timeout,
            retries=self._config.retries,
        )

    def _disconnect_client(self) -> None:
        if self._client:
            self._client.disconnect()

