from __future__ import annotations

from pathlib import Path


APP_NAME = "printer_modbus"
APP_ENVIRONMENT_ROOT = Path.home() / f".{APP_NAME}"
STORAGE_ROOT = APP_ENVIRONMENT_ROOT / "storage"
CONFIG_PATH = STORAGE_ROOT / "config.json"
SQLITE_PATH = APP_ENVIRONMENT_ROOT / "printer_modbus.db"
LOG_ROOT = STORAGE_ROOT / "logs"
LOG_PATH = LOG_ROOT / "printer_modbus.log"

