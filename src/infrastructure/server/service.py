from __future__ import annotations

import logging
import queue
import threading

from src.application.events import ServerRequestCompletedEvent
from src.infrastructure.server.api_client import ServerApiClient
from src.infrastructure.server.commands import (
    EndBatchCommand,
    PrintNextCommand,
    RePrintCommand,
    ServerCommand,
    StartBatchCommand,
)
from src.models.settings import ServerConfig


logger = logging.getLogger(__name__)


class ServerService:
    def __init__(
        self,
        config: ServerConfig,
        event_queue: queue.Queue[object],
        api_client: ServerApiClient | None = None,
    ) -> None:
        self._config = config
        self._event_queue = event_queue
        self._api_client = api_client or ServerApiClient(config)
        self._command_queue: queue.Queue[ServerCommand | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="server-worker",
            daemon=True,
        )
        self._thread.start()
        logger.info("Server service started")

    def stop(self) -> None:
        self._stop_event.set()
        self._command_queue.put(None)
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Server service stopped")

    def enqueue(self, command: ServerCommand) -> None:
        self._command_queue.put(command)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                command = self._command_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if command is None:
                return
            self._execute(command)

    def _execute(self, command: ServerCommand) -> None:
        if isinstance(command, PrintNextCommand):
            request_type = "print_next"
        elif isinstance(command, RePrintCommand):
            request_type = "reprint"
        elif isinstance(command, StartBatchCommand):
            request_type = "start_batch"
        elif isinstance(command, EndBatchCommand):
            request_type = "end_batch"
        else:
            logger.warning("Unsupported server command: %r", command)
            return

        if not self._config.enabled:
            error = "server service is disabled"
            logger.warning("Server %s request skipped: %s", request_type, error)
            self._publish_result(
                command=command,
                request_type=request_type,
                success=False,
                status_code=0,
                error=error,
            )
            return

        if isinstance(command, PrintNextCommand):
            response = self._api_client.print_next()
        elif isinstance(command, RePrintCommand):
            response = self._api_client.reprint()
        elif isinstance(command, StartBatchCommand):
            response = self._api_client.start_batch(command.box_count)
        else:
            response = self._api_client.end_batch()

        if response.success:
            logger.info(
                "Server %s request succeeded status=%s, payload=%s",
                request_type,
                response.status_code,
                response.payload,
            )
        else:
            logger.warning(
                "Server %s request failed status=%s error=%s",
                request_type,
                response.status_code,
                response.error,
            )
        self._publish_result(
            command=command,
            request_type=request_type,
            success=response.success,
            status_code=response.status_code,
            error=response.error,
            payload=response.payload,
        )

    def _publish_result(
        self,
        *,
        command: ServerCommand,
        request_type: str,
        success: bool,
        status_code: int,
        error: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._event_queue.put(
            ServerRequestCompletedEvent(
                request_type=request_type,
                operation_id=command.operation_id,
                success=success,
                status_code=status_code,
                error=error,
                payload=payload,
            )
        )
