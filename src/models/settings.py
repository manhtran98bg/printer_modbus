from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Self


def _to_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class DeviceConfig:
    device_id: str = "printer-001"
    device_name: str = "Printer Modbus"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            device_id=str(data.get("device_id") or "printer-001"),
            device_name=str(data.get("device_name") or "Printer Modbus"),
        )


@dataclass(slots=True)
class ModbusRTUSettings:
    port: str = "/dev/ttyUSB0"
    baud_rate: int = 9600
    data_bits: int = 8
    parity: str = "None"
    stop_bits: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            port=str(data.get("port") or "/dev/ttyUSB0"),
            baud_rate=_to_int(data.get("baud_rate"), 9600),
            data_bits=_to_int(data.get("data_bits"), 8),
            parity=str(data.get("parity") or "None"),
            stop_bits=_to_int(data.get("stop_bits"), 1),
        )


@dataclass(slots=True)
class ModbusTCPSettings:
    host: str = "127.0.0.1"
    port: int = 502

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            host=str(data.get("host") or "127.0.0.1"),
            port=_to_int(data.get("port"), 502),
        )


@dataclass(slots=True)
class ModbusConfig:
    enabled: bool = True
    modbus_type: str = "rtu"
    slave_id: int = 1
    poll_interval_ms: int = 1000
    timeout: int = 3
    retries: int = 1
    rtu: ModbusRTUSettings = field(default_factory=ModbusRTUSettings)
    tcp: ModbusTCPSettings = field(default_factory=ModbusTCPSettings)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        modbus_type = str(data.get("modbus_type") or "rtu").strip().lower()
        if modbus_type not in {"rtu", "tcp"}:
            modbus_type = "rtu"
        return cls(
            enabled=_to_bool(data.get("enabled"), True),
            modbus_type=modbus_type,
            slave_id=_to_int(data.get("slave_id"), 1),
            poll_interval_ms=max(100, _to_int(data.get("poll_interval_ms"), 1000)),
            timeout=max(1, _to_int(data.get("timeout"), 3)),
            retries=max(1, _to_int(data.get("retries"), 1)),
            rtu=ModbusRTUSettings.from_dict(data.get("rtu", {})),
            tcp=ModbusTCPSettings.from_dict(data.get("tcp", {})),
        )


@dataclass(slots=True)
class ServerConfig:
    enabled: bool = True
    base_url: str = "http://localhost:8000"
    token: str = ""
    timeout: int = 10
    retries: int = 3
    print_next_path: str = "/print-next"
    reprint_path: str = "/reprint"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            enabled=_to_bool(data.get("enabled"), True),
            base_url=str(data.get("base_url") or "http://localhost:8000"),
            token=str(data.get("token") or ""),
            timeout=max(1, _to_int(data.get("timeout"), 10)),
            retries=max(1, _to_int(data.get("retries"), 3)),
            print_next_path=str(data.get("print_next_path") or "/print-next"),
            reprint_path=str(data.get("reprint_path") or "/reprint"),
        )


@dataclass(slots=True)
class ServiceConfig:
    log_level: str = "INFO"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(log_level=str(data.get("log_level") or "INFO").upper())


@dataclass(slots=True)
class SettingsConfig:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    modbus: ModbusConfig = field(default_factory=ModbusConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            device=DeviceConfig.from_dict(data.get("device", {})),
            modbus=ModbusConfig.from_dict(data.get("modbus", {})),
            server=ServerConfig.from_dict(data.get("server", {})),
            service=ServiceConfig.from_dict(data.get("service", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

