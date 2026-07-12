#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/printer_modbus}"
SERVICE_NAME="printer_modbus.service"

sudo mkdir -p "${PROJECT_DIR}"
sudo cp -r ./src ./pyproject.toml ./README.md ./config.example.json "${PROJECT_DIR}/"
sudo cp "./scripts/${SERVICE_NAME}" "/etc/systemd/system/${SERVICE_NAME}"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"

echo "Installed ${SERVICE_NAME}. Start it with: sudo systemctl start ${SERVICE_NAME}"
