from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.models.settings import ServerConfig


@dataclass(frozen=True, slots=True)
class ServerResponse:
    success: bool
    status_code: int
    error: str = ""


class ServerApiClient:
    def __init__(self, config: ServerConfig) -> None:
        self._config = config

    def print_next(self) -> ServerResponse:
        return self._post_no_body(self._config.print_next_path)

    def reprint(self) -> ServerResponse:
        return self._post_no_body(self._config.reprint_path)

    def _post_no_body(self, path: str) -> ServerResponse:
        request = Request(self._url(path), method="POST", headers=self._headers())
        last_response = ServerResponse(success=False, status_code=0, error="request not sent")
        for _attempt in range(max(1, int(self._config.retries))):
            try:
                with urlopen(request, timeout=float(self._config.timeout)) as response:
                    status_code = int(response.status)
                    return ServerResponse(
                        success=200 <= status_code <= 299,
                        status_code=status_code,
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

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._config.token:
            headers["Authorization"] = f"Bearer {self._config.token}"
        return headers
