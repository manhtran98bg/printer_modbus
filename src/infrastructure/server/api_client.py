from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.models.settings import ServerConfig


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

    def start_batch(self, box_count: int) -> ServerResponse:
        return self._post_json(
            self._config.start_batch_path,
            {"box_count": int(box_count)},
        )

    def end_batch(self) -> ServerResponse:
        return self._post_no_body(self._config.end_batch_path)

    def _post_no_body(self, path: str) -> ServerResponse:
        return self._post_url(self._url(path))

    def _post_json(self, path: str, payload: dict[str, object]) -> ServerResponse:
        body = json.dumps(payload).encode("utf-8")
        return self._post_url(self._url(path), body=body)

    def _post_url(self, url: str, *, body: bytes | None = None) -> ServerResponse:
        request = Request(url, data=body, method="POST", headers=self._headers())
        last_response = ServerResponse(success=False, status_code=0, error="request not sent")
        attempts = max(1, int(self._config.retries))
        for attempt in range(attempts):
            try:
                with urlopen(request, timeout=float(self._config.timeout)) as response:
                    status_code = int(response.status)
                    payload = self._read_json_payload(response)
                    result = ServerResponse(
                        success=200 <= status_code <= 299,
                        status_code=status_code,
                        payload=payload,
                    )
                    if 500 <= status_code <= 599 and attempt + 1 < attempts:
                        last_response = result
                        continue
                    return result
            except HTTPError as exc:
                raw_body = exc.read()
                payload = self._decode_json_payload(raw_body)
                error = self._response_error(
                    payload,
                    raw_body.decode("utf-8", "ignore"),
                )
                last_response = ServerResponse(
                    success=False,
                    status_code=int(exc.code),
                    error=error,
                    payload=payload,
                )
                if 400 <= int(exc.code) <= 499:
                    return last_response
                if not 500 <= int(exc.code) <= 599:
                    return last_response
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
        return self._decode_json_payload(raw_body)

    @staticmethod
    def _decode_json_payload(raw_body: object) -> dict[str, object] | None:
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

    @staticmethod
    def _response_error(payload: dict[str, object] | None, fallback: str) -> str:
        if isinstance(payload, dict):
            message = payload.get("msg")
            if message is not None:
                return str(message)
        return fallback

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._config.token:
            headers["Authorization"] = f"Bearer {self._config.token}"
        return headers
