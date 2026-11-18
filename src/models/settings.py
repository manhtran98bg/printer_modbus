from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Self


DEFAULT_SERVER_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJlbWFpbCI6ImN1c3RvbWVyQGNvbXBhbnkuY29tIiwibmFtZSI6ImN1c3RvbWVyIiwicm9sZSI6ImN1c3RvbWVyIiwiaWF0IjoxNzcwNDQ4NzgxLCJleHAiOjQ5MjQwNDg3ODF9."
    "vRasF7iw_00cB3yURGMCO0A49pbvjcByhzcW6eTc1iU"
)


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
    base_url: str = "http://172.28.79.126:3412"
    token: str = DEFAULT_SERVER_TOKEN
    timeout: int = 10
    retries: int = 3
    start_batch_path: str = "/print-history/start-batch"
    print_next_path: str = "/print-history/next"
    reprint_path: str = "/print-history/re-print"
    end_batch_path: str = "/print-history/end-batch"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            enabled=_to_bool(data.get("enabled"), True),
            base_url=str(data.get("base_url") or "http://172.28.79.126:3412"),
            token=str(data.get("token") or DEFAULT_SERVER_TOKEN),
            timeout=max(1, _to_int(data.get("timeout"), 10)),
            retries=max(1, _to_int(data.get("retries"), 3)),
            start_batch_path=str(
                data.get("start_batch_path") or "/print-history/start-batch"
            ),
            print_next_path=str(data.get("print_next_path") or "/print-history/next"),
            reprint_path=str(data.get("reprint_path") or "/print-history/re-print"),
            end_batch_path=str(data.get("end_batch_path") or "/print-history/end-batch"),
        )


@dataclass(slots=True)
class ServiceConfig:
    log_level: str = "INFO"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(log_level=str(data.get("log_level") or "INFO").upper())


@dataclass(slots=True)
class DashboardConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    refresh_ms: int = 1000
    retention_days: int = 7

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            enabled=_to_bool(data.get("enabled"), True),
            host=str(data.get("host") or "0.0.0.0"),
            port=max(0, min(65535, _to_int(data.get("port"), 8080))),
            refresh_ms=max(500, _to_int(data.get("refresh_ms"), 1000)),
            retention_days=max(1, _to_int(data.get("retention_days"), 7)),
        )


@dataclass(slots=True)
class SettingsConfig:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    modbus: ModbusConfig = field(default_factory=ModbusConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            device=DeviceConfig.from_dict(data.get("device", {})),
            modbus=ModbusConfig.from_dict(data.get("modbus", {})),
            server=ServerConfig.from_dict(data.get("server", {})),
            service=ServiceConfig.from_dict(data.get("service", {})),
            dashboard=DashboardConfig.from_dict(data.get("dashboard", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

