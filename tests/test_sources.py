from datetime import UTC, datetime

from mainichi_news.config import SourceConfig
from mainichi_news.sources import google_news, rss, yahoo

GOOGLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>t</title>
<item>
  <title>松江で火事 - 山陰中央新報デジタル</title>
  <link>https://news.google.com/rss/articles/ABC?oc=5</link>
  <pubDate>Tue, 17 Nov 2026 09:50:00 GMT</pubDate>
  <source url="https://www.sanin-chuo.co.jp">山陰中央新報デジタル</source>
  <description>&lt;a href="https://x"&gt;松江で火事 - 山陰中央新報デジタル&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;山陰中央新報デジタル&lt;/font&gt;</description>
</item>
<item>
  <title>見出しだけ</title>
  <link>https://news.google.com/rss/articles/DEF?oc=5</link>
</item>
</channel></rss>"""

YAHOO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>松江で雪</title><link>https://yahoo/1</link></item>
<item><title>大阪で雪</title><link>https://yahoo/2</link></item>
</channel></rss>"""


def test_clean_title_removes_source_suffix_and_region():
    assert rss.clean_title("松江で火事 - 山陰中央新報", "山陰中央新報") == "松江で火事"
    assert rss.clean_title("松江で火事（山陰中央新報）") == "松江で火事"


def test_strip_html_and_parse_date():
    assert rss.strip_html("<a href='x'>見出し</a>&nbsp;媒体") == "見出し 媒体"
    parsed = rss.parse_date("Tue, 17 Nov 2026 09:50:00 GMT")
    assert parsed == datetime(2026, 11, 17, 9, 50, tzinfo=UTC)
    assert rss.parse_date("garbage") is None


def test_google_news_parse(monkeypatch):
    monkeypatch.setattr(rss, "fetch", lambda *a, **k: GOOGLE_XML.encode("utf-8"))
    articles = google_news.fetch_articles(SourceConfig(queries=["島根"]))
    assert len(articles) == 2
    first = articles[0]
    assert first.title == "松江で火事"
    assert first.source == "山陰中央新報デジタル"
    assert first.url.startswith("https://news.google.com/")
    assert first.summary == ""
    assert first.key


def test_google_news_fetch_failure_is_skipped(monkeypatch):
    def boom(*args, **kwargs):
        raise rss.FetchError("down")

    monkeypatch.setattr(rss, "fetch", boom)
    assert google_news.fetch_articles(SourceConfig()) == []


def test_yahoo_filters_non_shimane(monkeypatch):
    monkeypatch.setattr(rss, "fetch", lambda *a, **k: YAHOO_XML.encode("utf-8"))
    articles = yahoo.fetch_articles(SourceConfig())
    assert [a.title for a in articles] == ["松江で雪"]


def test_yahoo_is_shimane_keywords():
    assert yahoo.is_shimane("隠岐の島町でイベント") is True
    assert yahoo.is_shimane("東京で会見") is False


def test_feed_url_encodes_query():
    url = google_news.feed_url("島根 松江")
    assert "q=%E5%B3%B6%E6%A0%B9+%E6%9D%BE%E6%B1%9F" in url
    assert "hl=ja" in url


def test_install_templates_render(tmp_path):
    from string import Template

    from mainichi_news.install import template

    service = template("mainichi-news.service").substitute(
        workdir=tmp_path, exec_start="/usr/bin/python -m mainichi_news run"
    )
    assert "ExecStart=/usr/bin/python -m mainichi_news run" in service
    assert "$" not in service

    timer = Template(template("mainichi-news.timer").template).safe_substitute()
    assert "OnCalendar=*-*-* 06:00:00" in timer
