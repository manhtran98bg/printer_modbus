from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.foundation.paths import CONFIG_PATH
from src.models.settings import SettingsConfig


logger = logging.getLogger(__name__)


class SettingsRepository:
    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self._config_path = config_path

    @property
    def config_path(self) -> Path:
        return self._config_path

    def load(self) -> SettingsConfig:
        if not self._config_path.exists():
            logger.info("Config not found, creating default config path=%s", self._config_path)
            config = SettingsConfig()
            self.save(config)
            return config

        logger.info("Loading config path=%s", self._config_path)
        with self._config_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError(f"Config must be a JSON object: {self._config_path}")
        return SettingsConfig.from_dict(data)

    def save(self, config: SettingsConfig) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2)
        self._config_path.write_text(f"{payload}\n", encoding="utf-8")
        logger.info("Saved config path=%s", self._config_path)

    def update(self, data: dict[str, Any]) -> SettingsConfig:
        config = SettingsConfig.from_dict(data)
        self.save(config)
        return config

