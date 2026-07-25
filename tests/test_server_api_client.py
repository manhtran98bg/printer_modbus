from __future__ import annotations

import json

from src.infrastructure.server.api_client import ServerApiClient
from src.models.settings import DEFAULT_SERVER_TOKEN, ServerConfig


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def read(self) -> bytes:
        return self._body


def test_server_api_client_accepts_http_2xx(monkeypatch):
    def fake_urlopen(_request, timeout):
        assert timeout == 10
        return FakeResponse(204)

    monkeypatch.setattr("src.infrastructure.server.api_client.urlopen", fake_urlopen)

    response = ServerApiClient(ServerConfig()).print_next()

    assert response.success is True
    assert response.status_code == 204
    assert response.payload is None


def test_server_api_client_parses_http_2xx_json_payload(monkeypatch):
    payload = {"metaData": {"label_counting": 2}}

    def fake_urlopen(_request, timeout):
        assert timeout == 10
        return FakeResponse(200, json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("src.infrastructure.server.api_client.urlopen", fake_urlopen)

    response = ServerApiClient(ServerConfig()).start_batch()

    assert response.success is True
    assert response.status_code == 200
    assert response.payload == payload


def test_server_api_client_rejects_non_2xx(monkeypatch):
    def fake_urlopen(_request, timeout):
        return FakeResponse(302)

    monkeypatch.setattr("src.infrastructure.server.api_client.urlopen", fake_urlopen)

    response = ServerApiClient(ServerConfig()).reprint()

    assert response.success is False
    assert response.status_code == 302


def test_server_api_client_uses_bearer_headers():
    headers = ServerApiClient(ServerConfig())._headers()

    assert headers["Accept"] == "application/json"
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == f"Bearer {DEFAULT_SERVER_TOKEN}"


def test_server_config_token_defaults_and_can_be_overridden():
    assert ServerConfig().token == DEFAULT_SERVER_TOKEN
    assert ServerConfig.from_dict({"token": ""}).token == DEFAULT_SERVER_TOKEN
    assert ServerConfig.from_dict({"token": "custom-token"}).token == "custom-token"
