"""Vercel Python serverless handler bridging the FastAPI app (fdc.api:app).

The Vercel Python runtime exposes each handler file's ``handler`` callable as a
serverless function. Starlette/FastAPI is ASGI, so we invoke the app directly and
map ASGI events/results onto Vercel's ``{statusCode, headers, body}`` shape.
"""

from __future__ import annotations

import asyncio
import os
import sys

from urllib.parse import quote

_REPO_ROOT = os.environ.get("FDC_REPO_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
SRC_ROOT = os.path.join(_REPO_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from fdc.api import app


def handler(req):
    body = req.body or b""
    if isinstance(body, str):
        body = body.encode()

    raw_path = req.path or "/"
    path = raw_path.split("?", 1)[0]

    scope = {
        "type": "http",
        "asgi_version": "3.0",
        "http_version": "1.1",
        "method": (req.http_method or "GET").upper(),
        "scheme": "https",
        "path": path,
        "raw_path": path,
        "query_string": _query_bytes(req.query or {}),
        "root_path": "",
        "headers": _headers(req.headers or {}),
        "client": ("0.0.0.0", 0),
        "server": ("0.0.0.0", 443),
    }

    state: dict = {"status_code": 200, "headers": [], "body": b"", "done": False}
    result = asyncio.run(_run(scope, state, body))
    out_headers = {k.decode(): v.decode() for k, v in result["headers"]}
    out_body = result["body"].decode("utf-8", "replace")
    return {"statusCode": result["status_code"], "headers": out_headers, "body": out_body}


async def _run(scope: dict, state: dict, body: bytes) -> dict:
    received = {"value": False}

    async def receive():
        if not received["value"]:
            received["value"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict):
        mtype = message["type"]
        if mtype == "http.response.start":
            state["status_code"] = message["status"]
            state["headers"] = list(message.get("headers", []))
        elif mtype == "http.response.body":
            state["body"] += message.get("body", b"")
            if not message.get("more_body"):
                state["done"] = True

    await app(scope, receive, send)
    return state


def _query_bytes(query: dict) -> bytes:
    parts: list[str] = []
    for key, value in query.items():
        if isinstance(value, (list, tuple)):
            for item in value:
                parts.append(f"{quote(str(key), safe='')}={quote(str(item), safe='')}")
        else:
            parts.append(f"{quote(str(key), safe='')}={quote(str(value), safe='')}")
    return "&".join(parts).encode()


def _headers(raw: dict) -> list[tuple[bytes, bytes]]:
    out: list[tuple[bytes, bytes]] = []
    for key, value in raw.items():
        if key:
            out.append((str(key).encode(), str(value).encode()))
    return out
