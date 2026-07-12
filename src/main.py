from __future__ import annotations

import signal

from src.composition.container import ApplicationContainer


def main() -> int:
    container = ApplicationContainer()

    def request_shutdown(_signum: int, _frame: object) -> None:
        container.request_shutdown()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    try:
        container.start()
        container.run_forever()
    finally:
        container.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

