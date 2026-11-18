from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.infrastructure.dashboard.state import DashboardState
from src.models.settings import DashboardConfig


logger = logging.getLogger(__name__)


class DashboardService:
    def __init__(
        self,
        *,
        config: DashboardConfig,
        state: DashboardState,
        db_path: str | Path,
    ) -> None:
        self._config = config
        self._state = state
        self._db_path = Path(db_path)
        self._index_path = Path(__file__).with_name("index.html")
        self._logo_path = Path(__file__).with_name("nidec-logo.png")
        self._font_path = Path(__file__).with_name("roboto-variable.ttf")
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def bound_port(self) -> int:
        if self._server is None:
            return int(self._config.port)
        return int(self._server.server_address[1])

    def start(self) -> None:
        if not self._config.enabled or (self._thread and self._thread.is_alive()):
            return
        try:
            handler = self._build_handler()
            self._server = ThreadingHTTPServer(
                (self._config.host, int(self._config.port)),
                handler,
            )
            self._server.daemon_threads = True
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="dashboard-web",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                "Dashboard started url=http://%s:%s",
                self._config.host,
                self.bound_port,
            )
        except Exception:
            self._server = None
            self._thread = None
            logger.exception("Dashboard failed to start; print workflow remains active")

    def stop(self) -> None:
        server = self._server
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if self._thread:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        logger.info("Dashboard stopped")

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        service = self

        class DashboardRequestHandler(BaseHTTPRequestHandler):
            server_version = "PrinterDashboard/1.0"

            def do_GET(self) -> None:  # noqa: N802
                service._handle_get(self)

            def do_HEAD(self) -> None:  # noqa: N802
                service._handle_get(self, include_body=False)

            def do_POST(self) -> None:  # noqa: N802
                service._write_json(
                    self,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    {"error": "Dashboard is read-only"},
                )

            def log_message(self, format: str, *args: object) -> None:
                logger.debug("Dashboard request: " + format, *args)

        return DashboardRequestHandler

    def _handle_get(
        self,
        handler: BaseHTTPRequestHandler,
        *,
        include_body: bool = True,
    ) -> None:
        parsed = urlparse(handler.path)
        if parsed.path == "/":
            try:
                body = self._index_path.read_bytes()
            except OSError as exc:
                logger.warning("Dashboard UI could not be loaded: %s", exc)
                self._write_json(
                    handler,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "Dashboard UI is unavailable"},
                    include_body=include_body,
                )
                return
            self._write_response(
                handler,
                HTTPStatus.OK,
                body,
                "text/html; charset=utf-8",
                include_body=include_body,
            )
            return

        if parsed.path == "/nidec-logo.png":
            try:
                body = self._logo_path.read_bytes()
            except OSError as exc:
                logger.warning("Dashboard logo could not be loaded: %s", exc)
                self._write_json(
                    handler,
                    HTTPStatus.NOT_FOUND,
                    {"error": "Dashboard logo is unavailable"},
                    include_body=include_body,
                )
                return
            self._write_response(
                handler,
                HTTPStatus.OK,
                body,
                "image/png",
                include_body=include_body,
            )
            return

        if parsed.path == "/roboto-variable.ttf":
            try:
                body = self._font_path.read_bytes()
            except OSError as exc:
                logger.warning("Dashboard font could not be loaded: %s", exc)
                self._write_json(
                    handler,
                    HTTPStatus.NOT_FOUND,
                    {"error": "Dashboard font is unavailable"},
                    include_body=include_body,
                )
                return
            self._write_response(
                handler,
                HTTPStatus.OK,
                body,
                "font/ttf",
                include_body=include_body,
            )
            return

        if parsed.path == "/api/dashboard":
            query = parse_qs(parsed.query)
            try:
                requested_limit = int(query.get("limit", ["200"])[0])
            except ValueError:
                requested_limit = 200
            limit = max(1, min(500, requested_limit))
            payload = {
                "generated_at": int(time.time()),
                "refresh_ms": int(self._config.refresh_ms),
                "status": self._state.snapshot(),
                "batches": self._read_batches(),
                "events": self._read_events(limit),
            }
            self._write_json(
                handler,
                HTTPStatus.OK,
                payload,
                include_body=include_body,
            )
            return

        self._write_json(
            handler,
            HTTPStatus.NOT_FOUND,
            {"error": "Not found"},
            include_body=include_body,
        )

    def _read_events(self, limit: int) -> list[dict[str, object]]:
        if not self._db_path.exists():
            return []
        try:
            connection = sqlite3.connect(self._db_path, timeout=2)
            connection.row_factory = sqlite3.Row
            try:
                rows = connection.execute(
                    """
                    SELECT operation_id, batch_id, action, direction,
                           request_register, request_value,
                           response_register, response_value,
                           box_count, status, http_status, message,
                           started_at, completed_at, updated_at
                    FROM communication_event
                    ORDER BY updated_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
            finally:
                connection.close()
        except (OSError, sqlite3.Error) as exc:
            logger.warning("Dashboard failed to read events: %s", exc)
            return []
        return [dict(row) for row in rows]

    def _read_batches(self) -> list[dict[str, object]]:
        if not self._db_path.exists():
            return []
        try:
            connection = sqlite3.connect(self._db_path, timeout=2)
            connection.row_factory = sqlite3.Row
            try:
                rows = connection.execute(
                    """
                    SELECT batch_id, started_at, ended_at, status,
                           success_count, failed_count, created_at, updated_at
                    FROM batch_label_summary
                    ORDER BY started_at DESC, rowid DESC
                    """
                ).fetchall()
            finally:
                connection.close()
        except (OSError, sqlite3.Error) as exc:
            logger.warning("Dashboard failed to read batches: %s", exc)
            return []
        return [dict(row) for row in rows]

    def _write_json(
        self,
        handler: BaseHTTPRequestHandler,
        status: HTTPStatus,
        payload: object,
        *,
        include_body: bool = True,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._write_response(
            handler,
            status,
            body,
            "application/json; charset=utf-8",
            include_body=include_body,
        )

    @staticmethod
    def _write_response(
        handler: BaseHTTPRequestHandler,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        *,
        include_body: bool,
    ) -> None:
        handler.send_response(int(status))
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("X-Frame-Options", "DENY")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True
        if include_body:
            handler.wfile.write(body)
