from datetime import UTC, datetime
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import threading
from sqlalchemy.orm import sessionmaker

from fdc import news
from fdc.db import get_engine
from fdc.models import NewsItem, create_all_for_tests
from fdc.news import parse_reddit, parse_rss


def _make_handler(body: bytes):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return H


def test_fetch_falls_back_to_direct_when_configured_proxy_is_down(tmp_path, monkeypatch):
    """A configured but stopped Clash proxy must not block a direct fetch."""
    body = b'{"data":{"children":[]}}'
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(body))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Port 1 is reserved and down: models "Clash stopped".
        monkeypatch.setattr(
            news, "get_settings",
            lambda: SimpleNamespace(resolved_quotes_proxy="http://127.0.0.1:1"),
        )
        raw = news._fetch(f"http://127.0.0.1:{port}")
        assert raw == body
    finally:
        server.shutdown()


def test_fetch_direct_bypasses_environment_proxy(tmp_path, monkeypatch):
    """.env injects HTTP(S)_PROXY; a direct fetch must bypass it."""
    body = b'{"ok": true}'
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(body))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
        monkeypatch.setenv("https_proxy", "http://127.0.0.1:1")
        monkeypatch.setattr(news, "get_settings", lambda: SimpleNamespace(resolved_quotes_proxy=None))
        assert news._fetch(f"http://127.0.0.1:{port}/") == body
    finally:
        server.shutdown()


def test_read_news_reports_all_configured_sources_even_when_empty(tmp_path, monkeypatch):
    """The page must show every configured source; a blocked feed reports 0."""
    engine = get_engine(f"sqlite:///{tmp_path / 'news-cfg.db'}")
    create_all_for_tests(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(news, "FEEDS_PATH", tmp_path / "feeds.json")
    (tmp_path / "feeds.json").write_text(json.dumps([
        {"label": "CNBC", "kind": "rss", "url": "https://example.test/a", "enabled": True},
        {"label": "reddit/r/stocks", "kind": "reddit_json", "url": "https://example.test/b", "enabled": True},
    ]))
    now = datetime.now(UTC)
    with factory() as session, session.begin():
        session.add(NewsItem(source="CNBC", external_id="n1", title="Headline",
            url="https://example.test/n1", published_at=now, collected_at=now))
    result = news.read_news(per_source=5, session_factory=factory)
    assert {entry["source"]: entry["count"] for entry in result["sources"]} == {
        "CNBC": 1, "reddit/r/stocks": 0,
    }


def test_select_proxy_prefers_reachable_configured_proxy(tmp_path, monkeypatch):
    monkeypatch.setattr(
        news, "get_settings",
        lambda: SimpleNamespace(resolved_quotes_proxy="http://10.1.1.1:7890"),
    )
    monkeypatch.setattr(news, "proxy_reachable", lambda proxy, timeout=1.0: True)
    assert news._select_proxy() == "http://10.1.1.1:7890"


def test_select_proxy_returns_none_when_proxy_unreachable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        news, "get_settings",
        lambda: SimpleNamespace(resolved_quotes_proxy="http://10.1.1.1:7890"),
    )
    monkeypatch.setattr(news, "proxy_reachable", lambda proxy, timeout=1.0: False)
    assert news._select_proxy() is None




def test_parse_rss_extracts_news_items():
    xml = b'''<rss><channel><item><guid>story-1</guid><title>Market update</title>
    <link>https://example.com/story</link><pubDate>Mon, 23 Nov 2026 12:00:00 GMT</pubDate>
    </item></channel></rss>'''
    assert parse_rss(xml, "Example") == [{
        "external_id": "story-1",
        "title": "Market update",
        "url": "https://example.com/story",
        "source": "Example",
        "published_at": "2026-11-23T12:00:00+00:00",
    }]


def test_parse_reddit_extracts_posts_and_permalink():
    from fdc.news import parse_reddit

    payload = {"data": {"children": [{"data": {
        "id": "abc123", "title": "Market chatter", "permalink": "/r/stocks/comments/abc123/post/",
        "created_utc": 1795435200, "url": "https://example.com/article",
    }}]}}
    item = parse_reddit(payload, "reddit/r/stocks")[0]
    assert item["external_id"] == "abc123"
    assert item["url"] == "https://www.reddit.com/r/stocks/comments/abc123/post/"
def test_collect_deduplicates_news_across_runs(tmp_path, monkeypatch):
    engine = get_engine(f"sqlite:///{tmp_path / 'news.db'}")
    create_all_for_tests(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(news, "FEEDS_PATH", tmp_path / "feeds.json")
    (tmp_path / "feeds.json").write_text(json.dumps([{
        "label": "Example", "kind": "rss", "url": "https://example.test/feed", "enabled": True,
    }]))
    xml = b'''<rss><channel><item><guid>id-1</guid><title>Title</title>
    <link>https://example.test/story</link><pubDate>Mon, 23 Nov 2026 12:00:00 GMT</pubDate>
    </item></channel></rss>'''
    fetch = lambda url: xml

    assert news.collect(fetch=fetch, session_factory=factory) == 1
    assert news.collect(fetch=fetch, session_factory=factory) == 0
    with factory() as session:
        assert session.query(NewsItem).count() == 1


def test_read_news_returns_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_configured_sources", lambda: [])
    engine = get_engine(f"sqlite:///{tmp_path / 'news-read.db'}")
    create_all_for_tests(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    with factory() as session, session.begin():
        session.add_all([
            NewsItem(source="A", external_id="old", title="Old", url="https://example.test/old",
                     published_at=now.replace(year=2025), collected_at=now),
            NewsItem(source="A", external_id="new", title="New", url="https://example.test/new",
                     published_at=now, collected_at=now),
        ])
    result = news.read_news(1, session_factory=factory)
    assert [item["id"] for item in result["items"]] == ["new"]
    assert result["sources"] == [{"source": "A", "count": 2}]


def test_read_news_per_source_caps_each_source(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_configured_sources", lambda: [])
    engine = get_engine(f"sqlite:///{tmp_path / 'news-persource.db'}")
    create_all_for_tests(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    with factory() as session, session.begin():
        for source in ("CNBC", "reddit/r/stocks"):
            for index in range(3):
                session.add(NewsItem(
                    source=source, external_id=f"{source}-{index}", title=f"{source} {index}",
                    url=f"https://example.test/{source}-{index}",
                    published_at=now, collected_at=now,
                ))
    result = news.read_news(per_source=2, session_factory=factory)
    by_source = {}
    for item in result["items"]:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1
    # Two newest per source, and every source is represented.
    assert by_source == {"CNBC": 2, "reddit/r/stocks": 2}
    assert {entry["source"] for entry in result["sources"]} == {"CNBC", "reddit/r/stocks"}


def test_parse_rss_rejects_malformed_xml():
    import pytest

    with pytest.raises(Exception):
        parse_rss(b"<rss>", "Example")
