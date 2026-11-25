import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fdc.netutil import proxy_reachable


def test_proxy_reachable_false_for_absent_proxy():
    assert proxy_reachable(None) is False
    assert proxy_reachable("") is False


def test_proxy_reachable_false_when_port_is_down():
    # Port 1 is reserved and nothing listens on it.
    assert proxy_reachable("http://127.0.0.1:1") is False


def test_proxy_reachable_true_when_something_listens():
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert proxy_reachable(f"http://127.0.0.1:{port}") is True
    finally:
        server.shutdown()


def test_proxy_reachable_reads_port_from_url():
    assert proxy_reachable("http://10.0.0.1:7890", timeout=0.2) is False
