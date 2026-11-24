from datetime import UTC, datetime
import json
from sqlalchemy.orm import sessionmaker

from fdc import news
from fdc.db import get_engine
from fdc.models import NewsItem, create_all_for_tests
from fdc.news import parse_reddit, parse_rss



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


def test_read_news_returns_newest_first(tmp_path):
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


def test_parse_rss_rejects_malformed_xml():
    import pytest

    with pytest.raises(Exception):
        parse_rss(b"<rss>", "Example")
