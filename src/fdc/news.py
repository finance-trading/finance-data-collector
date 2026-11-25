"""Fetch and persist public RSS and Reddit news feeds."""
from __future__ import annotations

import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select

from fdc.config import get_settings
from fdc.data_files import PROJECT_ROOT
from fdc.db import SessionLocal
from fdc.models import NewsItem
from fdc.netutil import proxy_reachable

logger = logging.getLogger(__name__)
FEEDS_PATH = PROJECT_ROOT / "config" / "news_feeds.json"


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _safe_url(url: str) -> str | None:
    """Accept only http/https links from untrusted feed data."""
    scheme = urlparse(url).scheme.lower()
    return url if scheme in {"http", "https"} else None


def parse_rss(payload: bytes, source: str) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = _safe_url((item.findtext("link") or "").strip())
        external_id = (item.findtext("guid") or url or title).strip()
        date_text = item.findtext("pubDate")
        try:
            published = parsedate_to_datetime(date_text).astimezone(UTC) if date_text else None
        except (TypeError, ValueError, OverflowError):
            published = None
        if title and url and external_id:
            items.append({"external_id": external_id, "title": title, "url": url,
                          "source": source, "published_at": _iso(published)})
    return items


def parse_reddit(payload: dict[str, Any], source: str) -> list[dict[str, Any]]:
    items = []
    children = payload.get("data", {}).get("children", [])
    for child in children:
        post = child.get("data", {})
        post_id = str(post.get("id") or "").strip()
        title = str(post.get("title") or "").strip()
        permalink = str(post.get("permalink") or "").strip()
        if not post_id or not title or not permalink.startswith("/"):
            continue
        published = None
        try:
            published = datetime.fromtimestamp(float(post["created_utc"]), tz=UTC)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            pass
        items.append({"external_id": post_id, "title": title,
                      "url": f"https://www.reddit.com{permalink}", "source": source,
                      "published_at": _iso(published)})
    return items


def _feeds() -> list[dict[str, Any]]:
    try:
        feeds = json.loads(FEEDS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [feed for feed in feeds if isinstance(feed, dict) and feed.get("enabled", True)]


def _select_proxy() -> str | None:
    """Return the configured proxy only if it is actually running.

    The .env pins ``HTTPS_PROXY`` at the local Clash port; when Clash is
    stopped every fetch routed through it fails with "connection refused", so
    we probe the port and fall back to direct egress when it is down.
    """

    proxy = get_settings().resolved_quotes_proxy
    if proxy and proxy_reachable(proxy):
        return proxy
    return None


def _fetch(url: str) -> bytes:
    # CNBC's edge answers a generic/bot User-Agent with 403; a browser UA is
    # required. Reddit blocks datacenter egress, so route via the proxy too.
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
    request = urllib.request.Request(url, headers=headers)
    proxy = _select_proxy()
    if proxy:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        # An explicit empty ProxyHandler overrides the HTTPS_PROXY that .env
        # injects into the process; otherwise "direct" would still be routed
        # through a stopped Clash and fail with connection-refused.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=20) as response:
        return response.read(2_000_000)


def collect(fetch=_fetch, session_factory=SessionLocal) -> int:
    """Fetch configured sources; one source failure does not block others."""
    parsed: list[dict[str, Any]] = []
    for feed in _feeds():
        try:
            raw = fetch(feed["url"])
            if feed["kind"] == "rss":
                parsed.extend(parse_rss(raw, feed["label"]))
            elif feed["kind"] == "reddit_json":
                parsed.extend(parse_reddit(json.loads(raw), feed["label"]))
        except Exception:
            logger.warning("News feed failed: %s", feed.get("label", "unknown"), exc_info=True)
    inserted = 0
    with session_factory() as session, session.begin():
        for item in parsed:
            exists = session.scalar(select(NewsItem.id).where(
                NewsItem.source == item["source"], NewsItem.external_id == item["external_id"]))
            if exists:
                continue
            published_at = datetime.fromisoformat(item["published_at"]) if item["published_at"] else None
            row_data = {**item, "published_at": published_at, "collected_at": datetime.now(UTC)}
            session.add(NewsItem(**row_data))
            inserted += 1
    return inserted


def _configured_sources() -> list[str]:
    """Feed labels from the config, in declared order (for the news page)."""
    labels: list[str] = []
    for feed in _feeds():
        label = str(feed.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def read_news(limit: int = 40, per_source: int | None = None, session_factory=SessionLocal) -> dict[str, Any]:
    with session_factory() as session:
        if per_source:
            # Cap the newest items per source so no single feed crowds out the
            # rest: guarantees multi-source visibility on the news page.
            rows: list[NewsItem] = []
            for source in session.scalars(select(NewsItem.source).distinct()).all():
                rows.extend(session.scalars(select(NewsItem).where(NewsItem.source == source).order_by(
                    NewsItem.published_at.desc().nullslast(), NewsItem.collected_at.desc()
                ).limit(per_source)).all())
            rows.sort(key=lambda row: row.published_at or row.collected_at, reverse=True)
        else:
            rows = session.scalars(select(NewsItem).order_by(
                NewsItem.published_at.desc().nullslast(), NewsItem.collected_at.desc()
            ).limit(limit)).all()
        counts = dict(session.execute(select(NewsItem.source, func.count()).group_by(NewsItem.source)).all())

    # Merge configured sources (even blocked ones, at 0) with stored counts so
    # the page always shows the full multi-source set.
    ordered = _configured_sources()
    for source in counts:
        if source not in ordered:
            ordered.append(source)
    items = [{"id": row.external_id, "title": row.title, "url": row.url,
              "source": row.source, "published_at": _iso(row.published_at)} for row in rows]
    return {
        "as_of": _iso(rows[0].collected_at) if rows else None,
        "items": items,
        "sources": [{"source": source, "count": int(counts.get(source, 0))} for source in ordered],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"Inserted {collect()} news items")
