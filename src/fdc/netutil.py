"""Small network helpers shared by the collectors."""
from __future__ import annotations

import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def proxy_reachable(proxy: str | None, timeout: float = 1.0) -> bool:
    """True when a TCP connect to the proxy's host:port succeeds.

    Collectors use this to pick their egress route: a configured proxy that is
    not actually running (e.g. Clash is stopped) must not be used, otherwise
    every fetch fails fast with "connection refused".  A short probe keeps the
    decision cheap; the timeout only bounds the *probe*, not the fetch itself.
    """

    if not proxy:
        return False
    host, port = _proxy_host_port(proxy)
    if host is None or port is None:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _proxy_host_port(proxy: str) -> tuple[str | None, int | None]:
    parsed = urlparse(proxy if "://" in proxy else f"http://{proxy}")
    host = parsed.hostname
    if not host:
        return None, None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port
