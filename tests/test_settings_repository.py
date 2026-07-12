from __future__ import annotations

from src.foundation.paths import CONFIG_PATH
from src.infrastructure.settings_repository import SettingsRepository
from src.models.settings import SettingsConfig


def test_default_config_path_is_under_user_home():
    assert CONFIG_PATH.as_posix().endswith(".printer_modbus/storage/config.json")
    assert CONFIG_PATH.name == "config.json"


def test_settings_repository_creates_default_config(tmp_path):
    config_path = tmp_path / "storage" / "config.json"
    repository = SettingsRepository(config_path)

    config = repository.load()

    assert isinstance(config, SettingsConfig)
    assert config_path.exists()
    assert config.modbus.modbus_type == "rtu"


def test_settings_repository_loads_tcp_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
{
  "modbus": {
    "modbus_type": "tcp",
    "tcp": {
      "host": "192.168.1.10",
      "port": 1502
    }
  }
}
""",
        encoding="utf-8",
    )
    repository = SettingsRepository(config_path)

    config = repository.load()

    assert config.modbus.modbus_type == "tcp"
    assert config.modbus.tcp.host == "192.168.1.10"
    assert config.modbus.tcp.port == 1502

