from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.models.settings import ServerConfig


START_BATCH_URL = "http://172.28.79.126:3412/print-history/start-batch"
END_BATCH_URL = "http://172.28.79.126:3412/print-history/end-batch"


@dataclass(frozen=True, slots=True)
class ServerResponse:
    success: bool
    status_code: int
    error: str = ""
    payload: dict[str, object] | None = None


class ServerApiClient:
    def __init__(self, config: ServerConfig) -> None:
        self._config = config

    def print_next(self) -> ServerResponse:
        return self._post_no_body(self._config.print_next_path)

    def reprint(self) -> ServerResponse:
        return self._post_no_body(self._config.reprint_path)

    def start_batch(self) -> ServerResponse:
        return self._post_url_no_body(START_BATCH_URL)

    def end_batch(self) -> ServerResponse:
        return self._post_url_no_body(END_BATCH_URL)

    def _post_no_body(self, path: str) -> ServerResponse:
        return self._post_url_no_body(self._url(path))

    def _post_url_no_body(self, url: str) -> ServerResponse:
        request = Request(url, method="POST", headers=self._headers())
        last_response = ServerResponse(success=False, status_code=0, error="request not sent")
        for _attempt in range(max(1, int(self._config.retries))):
            try:
                with urlopen(request, timeout=float(self._config.timeout)) as response:
                    status_code = int(response.status)
                    payload = self._read_json_payload(response)
                    return ServerResponse(
                        success=200 <= status_code <= 299,
                        status_code=status_code,
                        payload=payload,
                    )
            except HTTPError as exc:
                last_response = ServerResponse(
                    success=False,
                    status_code=int(exc.code),
                    error=exc.read().decode("utf-8", "ignore"),
                )
            except (TimeoutError, URLError, OSError) as exc:
                last_response = ServerResponse(success=False, status_code=0, error=str(exc))
        return last_response

    def _url(self, path: str) -> str:
        base_url = self._config.base_url.rstrip("/")
        clean_path = "/" + str(path or "").lstrip("/")
        return f"{base_url}{clean_path}"

    def _read_json_payload(self, response: object) -> dict[str, object] | None:
        read = getattr(response, "read", None)
        if not callable(read):
            return None
        raw_body = read()
        if not raw_body:
            return None
        if isinstance(raw_body, bytes):
            text = raw_body.decode("utf-8", "ignore")
        else:
            text = str(raw_body)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            return payload
        return None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._config.token:
            headers["Authorization"] = f"Bearer {self._config.token}"
        return headers
