from datetime import UTC, date, datetime, timedelta

import pytest

from mainichi_news import state
from mainichi_news.dedupe import dedupe, make_key, normalize, within_window
from mainichi_news.models import Article, Digest, Story


def article(title, source="山陰中央新報", hours_ago=0, summary=""):
    published = datetime.now(UTC) - timedelta(hours=hours_ago)
    a = Article(title=title, url=f"https://example.com/{abs(hash(title))}", source=source,
                published=published, summary=summary)
    a.key = make_key(title)
    return a


def test_normalize_strips_media_tail_and_region_tag():
    assert normalize("松江で雪（島根）") == "松江で雪"
    assert normalize("事件が起きた | BSSニュース | BSS山陰放送") == "事件が起きた"
    assert normalize("事件 (1ページ)") == "事件"
    assert normalize("【速報】松江で火事") == "松江で火事"


def test_make_key_ignores_outlet():
    a = make_key("錦織圭さんに県民栄誉賞 - 山陰中央新報デジタル")
    b = make_key("錦織圭さんに県民栄誉賞")
    assert a == b


def test_dedupe_keeps_newest_and_merges_prefix_variants():
    older = article("松江市で大規模な火災が発生", hours_ago=5)
    newer = article("松江市で大規模な火災が発生 けが人なし", hours_ago=1)
    other = article("浜田市で子熊を目撃", hours_ago=2)
    result = dedupe([older, newer, other])
    assert len(result) == 2
    assert result[0].title == newer.title


def test_dedupe_similar_titles_merge():
    a = article(
        "海岸に身元不明の男性の遺体が打ち上がっているのを釣り場へ向かっていた男性が発見 島根県出雲市",
        hours_ago=1,
    )
    b = article(
        "腐敗が進み一部白骨化 海岸に身元不明の男性の遺体が打ち上がっているのを釣り場へ向かっていた男性が発見 島根県出雲市",
        hours_ago=2,
    )
    assert len(dedupe([a, b])) == 1


def test_within_window_drops_old_items_but_keeps_undated():
    fresh = article("新しい記事です", hours_ago=1)
    old = article("古い記事です", hours_ago=40)
    undated = Article(title="日付なし", url="https://example.com/x")
    result = within_window([fresh, old, undated], hours=24)
    assert {a.title for a in result} == {"新しい記事です", "日付なし"}


def test_state_guard_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MAINICHI_NEWS_STATE", str(tmp_path / "last-run"))
    today = date(2026, 11, 18)
    assert state.is_done(today) is False
    state.mark_done(today, articles=12, delivered="file:/x.md")
    assert state.is_done(today) is True
    assert state.is_done(date(2026, 11, 19)) is False
    assert state.last_run_info()["articles"] == "12"
    state.clear()
    assert state.is_done(today) is False


def test_digest_subject():
    digest = Digest(day=date(2026, 11, 11), one_liner="松江で初雪")
    assert digest.subject == "11/11(水) 島根 — 松江で初雪"


@pytest.fixture
def digest():
    return Digest(
        day=date(2026, 11, 11),
        one_liner="松江で初雪。県内は…",
        top=[Story(title="見出しA", summary="要約A", why="理由A", url="https://a",
                   source="山陰中央新報")],
        others=[Story(title="見出しB", summary="要約B", url="https://b", source="BSS")],
        numbers=["来場者 +12%"],
        article_count=7,
    )


def test_render_markdown(digest):
    from mainichi_news.format import render_markdown

    md = render_markdown(digest)
    assert "# 毎日ニュース 2026-11-11 (水) — 島根" in md
    assert "> 今日の一言: 松江で初雪。県内は…" in md
    assert "**なぜ重要**: 理由A" in md
    assert "[山陰中央新報](https://a)" in md
    assert "- 来場者 +12%" in md


def test_render_html_escapes(digest):
    from mainichi_news.format import render_html

    digest.top[0].title = "<script>alert(1)</script>"
    html = render_html(digest)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert digest.one_liner in html


def test_email_message_is_multipart(digest):
    from mainichi_news.config import Config
    from mainichi_news.deliver.email import EmailDeliverer

    cfg = Config()
    cfg.deliver.to = "to@example.com"
    cfg.deliver.sender = "from@example.com"
    cfg.deliver.smtp_host = "smtp.example.com"
    cfg.deliver.smtp_user = "from@example.com"
    cfg.deliver.smtp_password = "secret"
    message = EmailDeliverer(cfg).build_message(digest, digest.subject, "# md", "<p>html</p>")
    assert message["Subject"].startswith("【毎日ニュース】11/11(水) 島根")
    assert message.get_content_type() == "multipart/alternative"


def test_file_deliverer_writes_markdown(tmp_path, digest):
    from mainichi_news.deliver.file import FileDeliverer

    result = FileDeliverer(tmp_path).send(digest, digest.subject, "# md", "<p>x</p>")
    assert result.endswith("2026-11-11.md")
    assert (tmp_path / "2026-11-11.md").read_text(encoding="utf-8") == "# md"


def test_use_utf8_stdio_reconfigures_both_streams(monkeypatch):
    import sys

    from mainichi_news import cli

    calls = []

    class FakeStream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(sys, "stdout", FakeStream())
    monkeypatch.setattr(sys, "stderr", FakeStream())
    cli.use_utf8_stdio()
    assert calls == [{"encoding": "utf-8", "errors": "replace"}] * 2
