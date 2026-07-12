from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ModbusRTUConfig:
    port: str
    baud_rate: int
    data_bits: int
    parity: str
    stop_bits: int
    timeout: int
    retries: int = 1
    device_name: str = "Printer Modbus RTU"


@dataclass(frozen=True, slots=True)
class ModbusTCPConfig:
    host: str
    port: int = 502
    timeout: int = 3
    retries: int = 1
    device_name: str = "Printer Modbus TCP"


class ModbusClientProtocol(Protocol):
    @property
    def is_connected(self) -> bool:
        ...

    def connect(self, config: ModbusRTUConfig | ModbusTCPConfig) -> None:
        ...

    def disconnect(self) -> None:
        ...

    def read_holding_registers(self, slave_id: int, address: int, count: int) -> list[int]:
        ...

    def write_registers(self, slave_id: int, address: int, values: list[int]) -> None:
        ...


def normalize_modbus_parity(parity: str) -> str:
    value = str(parity or "").strip()
    if value in {"N", "E", "O"}:
        return value
    if value.lower() == "none":
        return "N"
    if value.lower() == "even":
        return "E"
    if value.lower() == "odd":
        return "O"
    return "N"


def _is_transport_exception(exc: Exception) -> bool:
    return isinstance(exc, (ConnectionError, OSError, TimeoutError))


class ModbusRTUClient:
    def __init__(self) -> None:
        self._client = None
        self._device_name = "Printer Modbus RTU"
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._connected and self._client.connected)

    def connect(self, config: ModbusRTUConfig) -> None:
        from pymodbus.client import ModbusSerialClient

        self.disconnect()
        self._device_name = config.device_name or "Printer Modbus RTU"
        self._client = ModbusSerialClient(
            port=config.port,
            baudrate=config.baud_rate,
            bytesize=config.data_bits,
            parity=normalize_modbus_parity(config.parity),
            retries=config.retries,
            stopbits=config.stop_bits,
            timeout=config.timeout,
        )
        if not self._client.connect():
            self.disconnect()
            raise ConnectionError(f"Cannot connect {self._device_name} port {config.port}")
        self._connected = True

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
        self._connected = False

    def read_holding_registers(self, slave_id: int, address: int, count: int) -> list[int]:
        if not self._client:
            raise ConnectionError(f"{self._device_name} client is not connected")
        result = self._execute_transport_call(
            lambda: self._client.read_holding_registers(
                address=address,
                count=count,
                device_id=slave_id,
            )
        )
        if result.isError():
            raise OSError(f"{self._device_name} read failed: {result}")
        return list(result.registers)

    def write_registers(self, slave_id: int, address: int, values: list[int]) -> None:
        if not self._client:
            raise ConnectionError(f"{self._device_name} client is not connected")
        result = self._execute_transport_call(
            lambda: self._client.write_registers(
                address=address,
                values=values,
                device_id=slave_id,
            )
        )
        if result.isError():
            raise OSError(f"{self._device_name} write failed: {result}")

    def _execute_transport_call(self, call: Callable[[], object]) -> object:
        try:
            return call()
        except Exception as exc:
            if _is_transport_exception(exc):
                self.disconnect()
            raise


class ModbusTCPClient:
    def __init__(self) -> None:
        self._client = None
        self._device_name = "Printer Modbus TCP"
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._connected and self._client.connected)

    def connect(self, config: ModbusTCPConfig) -> None:
        from pymodbus.client import ModbusTcpClient

        self.disconnect()
        self._device_name = config.device_name or "Printer Modbus TCP"
        self._client = ModbusTcpClient(
            host=config.host,
            port=config.port,
            retries=config.retries,
            timeout=config.timeout,
        )
        if not self._client.connect():
            self.disconnect()
            raise ConnectionError(
                f"Cannot connect {self._device_name} {config.host}:{config.port}"
            )
        self._connected = True

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
        self._connected = False

    def read_holding_registers(self, slave_id: int, address: int, count: int) -> list[int]:
        if not self._client:
            raise ConnectionError(f"{self._device_name} client is not connected")
        result = self._execute_transport_call(
            lambda: self._client.read_holding_registers(
                address=address,
                count=count,
                device_id=slave_id,
            )
        )
        if result.isError():
            raise OSError(f"{self._device_name} read failed: {result}")
        return list(result.registers)

    def write_registers(self, slave_id: int, address: int, values: list[int]) -> None:
        if not self._client:
            raise ConnectionError(f"{self._device_name} client is not connected")
        result = self._execute_transport_call(
            lambda: self._client.write_registers(
                address=address,
                values=values,
                device_id=slave_id,
            )
        )
        if result.isError():
            raise OSError(f"{self._device_name} write failed: {result}")

    def _execute_transport_call(self, call: Callable[[], object]) -> object:
        try:
            return call()
        except Exception as exc:
            if _is_transport_exception(exc):
                self.disconnect()
            raise

