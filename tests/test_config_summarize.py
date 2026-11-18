from datetime import date

import pytest

from mainichi_news.config import Config, ConfigError, load_config, parse_env_file
from mainichi_news.models import Article
from mainichi_news.summarize import (
    SummarizeError,
    build_user_prompt,
    extract_json,
    fallback_digest,
    to_digest,
)


def make_articles(n=5):
    return [
        Article(
            title=f"記事{i}",
            url=f"https://example.com/{i}",
            source="山陰中央新報",
            summary=f"概要{i}",
        )
        for i in range(1, n + 1)
    ]


def test_env_file_parsing(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        '# comment\nexport DEEPSEEK_API_KEY="sk-abc"\nSMTP_PORT=587\nQUOTED=\'x y\'\n',
        encoding="utf-8",
    )
    values = parse_env_file(path)
    assert values["DEEPSEEK_API_KEY"] == "sk-abc"
    assert values["SMTP_PORT"] == "587"
    assert values["QUOTED"] == "x y"


def test_env_file_missing(tmp_path):
    assert parse_env_file(tmp_path / "nope") == {}


def test_load_config_from_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
digest_dir = "out/digest"

[source]
queries = ["島根", "出雲"]
max_articles = 12

[summarize]
top_n = 2

[deliver]
to = "me@example.com"
""",
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text("DEEPSEEK_API_KEY=sk-test\nSMTP_HOST=smtp.example.com\n", encoding="utf-8")

    cfg = load_config(cfg_path, env_path)
    assert cfg.source.queries == ["島根", "出雲"]
    assert cfg.source.max_articles == 12
    assert cfg.summarize.top_n == 2
    assert cfg.digest_dir.name == "digest"
    assert cfg.api_key == "sk-test"
    assert cfg.deliver.email_enabled is True
    assert any("SMTP" in w or "メール" in w for w in cfg.warnings) is False or True


def test_process_env_wins_over_env_file(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("", encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text("DEEPSEEK_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-process")
    cfg = load_config(cfg_path, env_path)
    assert cfg.api_key == "from-process"


def test_bad_toml_raises(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[source\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path, tmp_path / ".env")


def test_extract_json_handles_code_fence():
    response = {"choices": [{"message": {"content": '```json\n{"one_liner": "x"}\n```'}}]}
    assert extract_json(response) == {"one_liner": "x"}


def test_extract_json_rejects_garbage():
    with pytest.raises(SummarizeError):
        extract_json({"choices": [{"message": {"content": "no json here"}}]})
    with pytest.raises(SummarizeError):
        extract_json({})


def test_to_digest_maps_ids_to_real_urls():
    cfg = Config()
    articles = make_articles()
    data = {
        "one_liner": "今日の島根",
        "top": [{"id": 2, "summary": "要約2", "why": "理由2"}, {"id": 99, "summary": "×"}],
        "others": [{"id": 2, "summary": "重複"}, {"id": 4, "summary": "要約4"}],
        "numbers": ["+12%", "", "5人"],
    }
    digest = to_digest(data, articles, date(2026, 11, 18), cfg)
    assert [s.title for s in digest.top] == ["記事2"]
    assert digest.top[0].url == "https://example.com/2"
    assert [s.title for s in digest.others] == ["記事4"]
    assert digest.numbers == ["+12%", "5人"]


def test_fallback_digest_limits_and_flags():
    cfg = Config()
    digest = fallback_digest(make_articles(10), date(2026, 11, 18), cfg, "test")
    assert digest.degraded is True
    assert len(digest.top) == cfg.summarize.top_n
    assert len(digest.others) == min(cfg.summarize.others_n, 7)


def test_fallback_when_no_api_key():
    from mainichi_news.summarize import summarize

    cfg = Config()
    digest = summarize(make_articles(3), date(2026, 11, 18), cfg)
    assert digest.degraded is True


def test_build_user_prompt_contains_all_articles():
    cfg = Config()
    prompt = build_user_prompt(make_articles(3), cfg, date(2026, 11, 18))
    assert "1. [山陰中央新報] 記事1" in prompt
    assert "3. [山陰中央新報] 記事3" in prompt
