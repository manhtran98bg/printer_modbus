from __future__ import annotations

import io
import json
import queue
from urllib.error import HTTPError, URLError

from src.application.events import ServerRequestCompletedEvent
from src.infrastructure.server.api_client import ServerApiClient
from src.infrastructure.server.commands import PrintNextCommand
from src.infrastructure.server.service import ServerService
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


def test_start_batch_posts_box_count_json_to_configured_url(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data
        captured["timeout"] = timeout
        return FakeResponse(200)

    monkeypatch.setattr("src.infrastructure.server.api_client.urlopen", fake_urlopen)

    response = ServerApiClient(ServerConfig()).start_batch(12)

    assert response.success is True
    assert captured == {
        "url": "http://172.28.79.126:3412/print-history/start-batch",
        "body": b'{"box_count": 12}',
        "timeout": 10.0,
    }


def test_no_body_endpoints_use_configured_paths(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, request.data, timeout))
        return FakeResponse(204)

    monkeypatch.setattr("src.infrastructure.server.api_client.urlopen", fake_urlopen)
    client = ServerApiClient(ServerConfig())

    assert client.print_next().success is True
    assert client.reprint().success is True
    assert client.end_batch().success is True
    assert requests == [
        ("http://172.28.79.126:3412/print-history/next", None, 10.0),
        ("http://172.28.79.126:3412/print-history/re-print", None, 10.0),
        ("http://172.28.79.126:3412/print-history/end-batch", None, 10.0),
    ]


def test_4xx_returns_immediately_and_parses_msg(monkeypatch):
    calls = 0

    def fake_urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        body = json.dumps({"msg": "box_count is invalid"}).encode("utf-8")
        raise HTTPError(
            url="http://example.test/start-batch",
            code=422,
            msg="unprocessable",
            hdrs=None,
            fp=io.BytesIO(body),
        )

    monkeypatch.setattr("src.infrastructure.server.api_client.urlopen", fake_urlopen)

    response = ServerApiClient(ServerConfig(retries=3)).start_batch(0)

    assert calls == 1
    assert response.success is False
    assert response.status_code == 422
    assert response.error == "box_count is invalid"
    assert response.payload == {"msg": "box_count is invalid"}


def test_4xx_parses_message_field(monkeypatch):
    body = json.dumps(
        {
            "statusCode": 404,
            "message": 'No print history with status "new" found',
        }
    ).encode("utf-8")

    def fake_urlopen(request, timeout):
        raise HTTPError(
            url=request.full_url,
            code=404,
            msg="not found",
            hdrs=None,
            fp=io.BytesIO(body),
        )

    monkeypatch.setattr("src.infrastructure.server.api_client.urlopen", fake_urlopen)

    response = ServerApiClient(ServerConfig()).start_batch(4)

    assert response.status_code == 404
    assert response.error == 'No print history with status "new" found'
    assert response.payload == {
        "statusCode": 404,
        "message": 'No print history with status "new" found',
    }


def test_5xx_retries_up_to_configured_attempts(monkeypatch):
    calls = 0

    def fake_urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        raise HTTPError(
            url="http://example.test/next",
            code=503,
            msg="unavailable",
            hdrs=None,
            fp=io.BytesIO(b'{"msg":"MES unavailable"}'),
        )

    monkeypatch.setattr("src.infrastructure.server.api_client.urlopen", fake_urlopen)

    response = ServerApiClient(ServerConfig(retries=3)).print_next()

    assert calls == 3
    assert response.success is False
    assert response.status_code == 503
    assert response.error == "MES unavailable"


def test_network_error_retries_up_to_configured_attempts(monkeypatch):
    calls = 0

    def fake_urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        raise URLError("network down")

    monkeypatch.setattr("src.infrastructure.server.api_client.urlopen", fake_urlopen)

    response = ServerApiClient(ServerConfig(retries=2)).reprint()

    assert calls == 2
    assert response.success is False
    assert response.status_code == 0
    assert "network down" in response.error


def test_server_api_client_uses_bearer_headers():
    headers = ServerApiClient(ServerConfig())._headers()

    assert headers["Accept"] == "application/json"
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == f"Bearer {DEFAULT_SERVER_TOKEN}"


def test_server_config_paths_default_and_can_be_overridden():
    config = ServerConfig.from_dict({"print_next_path": "/custom-next"})

    assert config.start_batch_path == "/print-history/start-batch"
    assert config.print_next_path == "/custom-next"
    assert config.reprint_path == "/print-history/re-print"
    assert config.end_batch_path == "/print-history/end-batch"


def test_disabled_server_publishes_technical_completion():
    event_queue: queue.Queue[object] = queue.Queue()
    service = ServerService(
        config=ServerConfig(enabled=False),
        event_queue=event_queue,
    )
    command = PrintNextCommand(operation_id="op-1")

    service._execute(command)

    event = event_queue.get_nowait()
    assert event == ServerRequestCompletedEvent(
        request_type="print_next",
        operation_id="op-1",
        success=False,
        status_code=0,
        error="server service is disabled",
        payload=None,
    )
