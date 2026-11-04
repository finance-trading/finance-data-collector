#!/usr/bin/env python3
"""Client CLI for the Finance Data Collector research-annotation API.

Read position bands (observe / entry / add / reduce) and watch items for one
ticker, and update them.  Reads need no credential; writes need the shared
API key the service operator configured (FDC_API_KEY server-side).

Configuration, in priority order:
  --base <origin>  / FDC_API_BASE   service origin; falls back to DEFAULT_API_BASE
  --key <bearer>   / FDC_API_KEY    API key; falls back to the bundled DEFAULT_API_KEY

Exit codes: 0 ok, 1 server or data error, 2 configuration or usage error.
Standard library only — no dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

BANDS = ("observe", "entry", "add", "reduce")
#: Operator defaults baked into the skill so external users work out of the box.
#: Precedence: --flag > FDC_API_BASE / FDC_API_KEY env vars > these constants.
DEFAULT_API_BASE = "http://127.0.0.1:8000"
DEFAULT_API_KEY = "0aac13278aa8c46dbae3403112c4f4edf84e1129c89dd4dd9f7f03d1810e04cb"


def fail(message: str, code: int) -> None:
    print(f"fdc-annotations: {message}", file=sys.stderr)
    sys.exit(code)


def config(args: argparse.Namespace) -> tuple[str, str | None]:
    base = (
        args.base
        or os.environ.get("FDC_API_BASE", "").rstrip("/")
        or DEFAULT_API_BASE
    )
    key = args.key or os.environ.get("FDC_API_KEY") or DEFAULT_API_KEY
    return base, key


def request(
    method: str, base: str, path: str, key: str | None, body: Any | None
) -> Any:
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode() or "null")
            return payload
    except urllib.error.HTTPError as error:
        raw = error.read().decode(errors="replace")
        try:
            detail = json.loads(raw).get("detail", raw)
        except (ValueError, AttributeError):
            detail = raw or error.reason
        hint = {
            401: "the service requires an API key for writes: set FDC_API_KEY or pass --key",
            403: "write rejected: the service is in local-only mode (no FDC_API_KEY configured server-side)",
            404: "unknown ticker or service path — check the ticker is in the AI universe and FDC_API_BASE is the service origin",
            422: "payload rejected: ranges need positive low<=high or both null; watch items need priority 1-3 and non-blank text (max 500 chars, max 50 items)",
        }.get(error.code, "")
        suffix = f" ({hint})" if hint else ""
        fail(f"HTTP {error.code} from {url}: {detail}{suffix}", 1)
    except urllib.error.URLError as error:
        fail(f"cannot reach {url}: {error.reason}", 1)
    return None


def get_annotation(base: str, key: str | None, ticker: str) -> dict[str, Any]:
    return request("GET", base, f"/api/v1/research/annotations/{ticker.upper()}", key, None)


def save_annotation(
    base: str, key: str | None, ticker: str, payload: dict[str, Any]
) -> dict[str, Any]:
    return request(
        "POST", base, f"/api/v1/research/annotations/{ticker.upper()}", key, payload
    )


def parse_band(value: str | list[str] | None) -> dict[str, float | None] | None:
    """['120','140'] -> {low:120, high:140}; ['null','null'] -> clear; None -> untouched."""
    if value is None:
        return None
    parts = value.split() if isinstance(value, str) else list(value)
    if len(parts) != 2:
        fail("bands take exactly two prices: LOW HIGH (or 'null null' to clear)", 2)
    if parts == ["null", "null"]:
        return {"low": None, "high": None}
    try:
        low, high = float(parts[0]), float(parts[1])
    except ValueError:
        fail(f"band {value!r} is not two numbers", 2)
    if low <= 0 or high <= 0:
        fail("band prices must be positive", 2)
    if low > high:
        fail(f"band low {low} exceeds high {high}", 2)
    return {"low": low, "high": high}


def cmd_set(args: argparse.Namespace) -> None:
    base, key = config(args)
    payload: dict[str, Any] = {}
    for band in BANDS:
        value = getattr(args, band)
        parsed = parse_band(value)
        if parsed is not None:
            payload[band + "_range"] = parsed
    if not payload:
        fail("nothing to update: pass at least one band flag", 2)
    result = save_annotation(base, key, args.ticker, payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_get(args: argparse.Namespace) -> None:
    base, key = config(args)
    result = get_annotation(base, key, args.ticker)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _watch_items(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "priority": item["priority"],
            "text": item["text"],
            **({"code": item["code"]} if item.get("code") else {}),
            **({"created_at": item["created_at"]} if item.get("created_at") else {}),
            **({"next_check_at": item["next_check_at"]} if item.get("next_check_at") else {}),
        }
        for item in view.get("watch_items", [])
    ]


def _find_item(items: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    matches = [item for item in items if item["text"].strip() == text.strip()]
    if not matches:
        listing = "; ".join(f"[P{item['priority']}] {item['text']}" for item in items) or "(none)"
        fail(f"no watch item with text {text!r}. Current items: {listing}", 1)
    if len(matches) > 1:
        fail(f"watch item text {text!r} is ambiguous ({len(matches)} matches)", 1)
    return matches


def _replace_watch_list(base: str, key: str | None, ticker: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    # The API replaces the whole list, so watch mutations always fetch first,
    # keep each surviving item's created_at, and send the full list back.
    payload = {"watch_items": items}
    return save_annotation(base, key, ticker, payload)


def parse_next_check(value: str) -> str:
    """'YYYY-MM-DD' or ISO datetime -> ISO string; 'null' clears it."""
    if value == "null":
        return "null"
    try:
        datetime.fromisoformat(value)
    except ValueError:
        fail(f"--next-check {value!r} is not a date (YYYY-MM-DD) or ISO datetime", 2)
    return value


def cmd_watch_list(args: argparse.Namespace) -> None:
    base, key = config(args)
    view = get_annotation(base, key, args.ticker)
    for item in view.get("watch_items", []):
        stamp = f" (added {item['created_at']})" if item.get("created_at") else ""
        nxt = f" (next {item['next_check_at']})" if item.get("next_check_at") else ""
        code = f"[{item['code']}] " if item.get("code") else ""
        print(f"[P{item['priority']}] {code}{item['text']}{stamp}{nxt}")


def cmd_watch_add(args: argparse.Namespace) -> None:
    base, key = config(args)
    view = get_annotation(base, key, args.ticker)
    items = _watch_items(view)
    if len(items) >= 50:
        fail("already at the 50-item cap; remove one first", 1)
    if any(item["text"].strip() == args.text.strip() for item in items):
        fail(f"item already exists: {args.text!r}", 1)
    new_item: dict[str, Any] = {"priority": args.priority, "text": args.text.strip()}
    # No created_at here: the server stamps it on creation.
    if args.code:
        new_item["code"] = args.code
    if args.next_check and args.next_check != "null":
        new_item["next_check_at"] = parse_next_check(args.next_check)
    items.append(new_item)
    print(json.dumps(_replace_watch_list(base, key, args.ticker, items), ensure_ascii=False, indent=2))


def cmd_watch_edit(args: argparse.Namespace) -> None:
    base, key = config(args)
    view = get_annotation(base, key, args.ticker)
    items = _watch_items(view)
    target = _find_item(items, args.text)[0]
    if args.new_text is not None:
        target["text"] = args.new_text.strip()
    if args.priority is not None:
        target["priority"] = args.priority
    if args.code is not None:
        if args.code == "null":
            target.pop("code", None)
        else:
            target["code"] = args.code
    if args.next_check is not None:
        if args.next_check == "null":
            target.pop("next_check_at", None)
        else:
            target["next_check_at"] = parse_next_check(args.next_check)
    print(json.dumps(_replace_watch_list(base, key, args.ticker, items), ensure_ascii=False, indent=2))


def cmd_watch_remove(args: argparse.Namespace) -> None:
    base, key = config(args)
    view = get_annotation(base, key, args.ticker)
    items = _watch_items(view)
    target = _find_item(items, args.text)[0]
    items.remove(target)
    print(json.dumps(_replace_watch_list(base, key, args.ticker, items), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fdc_annotations.py",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument("--base", help="service origin; default $FDC_API_BASE, else the bundled default")
    parser.add_argument("--key", help="API key; default $FDC_API_KEY, else the bundled key")
    sub = parser.add_subparsers(dest="command", required=True)

    pos = sub.add_parser("get", help="show bands and watch items for a ticker")
    pos.add_argument("ticker")
    pos.set_defaults(func=cmd_get)

    setp = sub.add_parser("set", help="update one or more price bands")
    setp.add_argument("ticker")
    for band in BANDS:
        setp.add_argument(
            f"--{band}",
            nargs=2,
            metavar=("LOW", "HIGH"),
            help=f"{band} band, two prices (or 'null null' to clear it)",
        )
    setp.set_defaults(func=cmd_set)

    watch = sub.add_parser("watch", help="manage the watch-item list")
    watch.add_argument("ticker")
    wsub = watch.add_subparsers(dest="watch_command", required=True)
    for name, help_text in (
        ("list", "list watch items with priority, code, and attention times"),
        ("add", "append a new item (server stamps created_at)"),
        ("edit", "change an item's text, priority, code or next check (created_at kept)"),
        ("remove", "delete an item"),
    ):
        w = wsub.add_parser(name, help=help_text)
        if name in ("add", "edit", "remove"):
            w.add_argument("text", help="item text (exact, stripped for matching)")
        if name == "add":
            w.add_argument("--priority", type=int, choices=(1, 2, 3), default=2)
            w.add_argument("--code", help="classification tag, e.g. FIN / 财报 (max 32 chars)")
            w.add_argument("--next-check", help="next attention date, YYYY-MM-DD or ISO datetime")
        if name == "edit":
            w.add_argument("--priority", type=int, choices=(1, 2, 3), default=None,
                          help="new priority (leave unset to keep)")
            w.add_argument("--new-text", help="replacement text")
            w.add_argument("--code", help="new classification tag ('null' clears)")
            w.add_argument("--next-check", help="new attention date ('null' clears)")
        w.set_defaults(
            func={"list": cmd_watch_list, "add": cmd_watch_add,
                  "edit": cmd_watch_edit, "remove": cmd_watch_remove}[name]
        )

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
