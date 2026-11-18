"""Configuration loading (config.toml + .env, env vars win)."""

from __future__ import annotations

import os
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "mainichi-news"

DEFAULT_USER_AGENT = "mainichi-news/0.1 (+https://github.com/KakkoiSchool/mainichi-news)"

# Keys that are secrets. Only read from the environment / .env file.
SECRET_KEYS = (
    "DEEPSEEK_API_KEY",
    "SMTP_PASSWORD",
    "SMTP_USER",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_FROM",
    "SMTP_TO",
    "MAINICHI_NEWS_TO",
)


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME


def default_config_path() -> Path:
    override = os.environ.get("MAINICHI_NEWS_CONFIG")
    if override:
        return Path(override).expanduser()
    local = Path("config.toml")
    if local.is_file():
        return local.resolve()
    return config_dir() / "config.toml"


def default_env_path() -> Path:
    override = os.environ.get("MAINICHI_NEWS_ENV")
    if override:
        return Path(override).expanduser()
    return config_dir() / ".env"


def parse_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser (quotes and `export` supported)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif value:
            try:
                parts = shlex.split(value, comments=True)
                value = parts[0] if parts else ""
            except ValueError:
                pass
        values[key] = value
    return values


@dataclass
class SourceConfig:
    queries: list[str] = field(default_factory=lambda: ["島根", "松江"])
    yahoo_enabled: bool = True
    yahoo_url: str = "https://news.yahoo.co.jp/rss/topics/local.xml"
    window_hours: int = 30
    max_articles: int = 30
    max_per_query: int = 40
    timeout: float = 20.0
    user_agent: str = DEFAULT_USER_AGENT


@dataclass
class SummarizeConfig:
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    top_n: int = 3
    others_n: int = 8
    max_body_chars: int = 1200
    timeout: float = 90.0
    temperature: float = 0.3
    retries: int = 1


@dataclass
class DeliverConfig:
    to: str = ""
    sender: str = ""
    subject_prefix: str = "【毎日ニュース】"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_starttls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""

    @property
    def email_enabled(self) -> bool:
        return bool(self.to and self.smtp_host)


@dataclass
class ArchiveConfig:
    enabled: bool = True
    push: bool = True
    remote: str = "origin"
    branch: str = ""


@dataclass
class Config:
    source: SourceConfig = field(default_factory=SourceConfig)
    summarize: SummarizeConfig = field(default_factory=SummarizeConfig)
    deliver: DeliverConfig = field(default_factory=DeliverConfig)
    archive: ArchiveConfig = field(default_factory=ArchiveConfig)
    digest_dir: Path = field(default_factory=lambda: Path("digest"))
    config_path: Path | None = None
    env_path: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def secret(self, key: str, default: str = "") -> str:
        return os.environ.get(key) or self.env.get(key) or default

    @property
    def api_key(self) -> str:
        return self.secret("DEEPSEEK_API_KEY")


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _section(data: dict, name: str) -> dict:
    value = data.get(name, {})
    return value if isinstance(value, dict) else {}


def load_config(path: Path | None = None, env_path: Path | None = None) -> Config:
    cfg = Config()
    cfg.config_path = Path(path).expanduser() if path else default_config_path()
    cfg.env_path = Path(env_path).expanduser() if env_path else default_env_path()
    cfg.env = parse_env_file(cfg.env_path)

    data: dict = {}
    if cfg.config_path.is_file():
        try:
            data = tomllib.loads(cfg.config_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"config.toml の解析に失敗: {exc}") from exc
    else:
        cfg.warnings.append(f"config.toml が見つからないので既定値で動作: {cfg.config_path}")

    src = _section(data, "source")
    if "queries" in src:
        queries = [str(q) for q in src["queries"] if str(q).strip()]
        if queries:
            cfg.source.queries = queries
    cfg.source.yahoo_enabled = _as_bool(src.get("yahoo", cfg.source.yahoo_enabled), True)
    cfg.source.yahoo_url = str(src.get("yahoo_url", cfg.source.yahoo_url))
    cfg.source.window_hours = int(src.get("window_hours", cfg.source.window_hours))
    cfg.source.max_articles = int(src.get("max_articles", cfg.source.max_articles))
    cfg.source.max_per_query = int(src.get("max_per_query", cfg.source.max_per_query))
    cfg.source.timeout = float(src.get("timeout", cfg.source.timeout))
    cfg.source.user_agent = str(src.get("user_agent", cfg.source.user_agent))

    sm = _section(data, "summarize")
    cfg.summarize.model = str(sm.get("model", cfg.summarize.model))
    cfg.summarize.base_url = str(sm.get("base_url", cfg.summarize.base_url)).rstrip("/")
    cfg.summarize.top_n = int(sm.get("top_n", cfg.summarize.top_n))
    cfg.summarize.others_n = int(sm.get("others_n", cfg.summarize.others_n))
    cfg.summarize.max_body_chars = int(sm.get("max_body_chars", cfg.summarize.max_body_chars))
    cfg.summarize.timeout = float(sm.get("timeout", cfg.summarize.timeout))
    cfg.summarize.temperature = float(sm.get("temperature", cfg.summarize.temperature))
    cfg.summarize.retries = int(sm.get("retries", cfg.summarize.retries))

    dl = _section(data, "deliver")
    cfg.deliver.to = str(dl.get("to", "") or cfg.secret("MAINICHI_NEWS_TO"))
    cfg.deliver.sender = str(
        dl.get("from", "") or cfg.secret("SMTP_FROM") or cfg.deliver.to
    )
    cfg.deliver.subject_prefix = str(dl.get("subject_prefix", cfg.deliver.subject_prefix))
    cfg.deliver.smtp_host = cfg.secret("SMTP_HOST")
    cfg.deliver.smtp_port = int(cfg.secret("SMTP_PORT", "587") or 587)
    cfg.deliver.smtp_starttls = _as_bool(
        cfg.secret("SMTP_STARTTLS", "true"), True
    )
    cfg.deliver.smtp_user = cfg.secret("SMTP_USER")
    cfg.deliver.smtp_password = cfg.secret("SMTP_PASSWORD")
    cfg.deliver.to = cfg.deliver.to or cfg.secret("SMTP_TO")

    ar = _section(data, "archive")
    cfg.archive.enabled = _as_bool(ar.get("enabled", cfg.archive.enabled), True)
    cfg.archive.push = _as_bool(ar.get("push", cfg.archive.push), True)
    cfg.archive.remote = str(ar.get("remote", cfg.archive.remote))
    cfg.archive.branch = str(ar.get("branch", cfg.archive.branch))

    digest_dir = data.get("digest_dir")
    if digest_dir:
        cfg.digest_dir = Path(str(digest_dir)).expanduser()
    else:
        cfg.digest_dir = Path.cwd() / "digest"

    if not cfg.deliver.email_enabled:
        cfg.warnings.append("メール設定が未完了（SMTP_HOST / to が空）→ 保存のみ")
    if not cfg.api_key:
        cfg.warnings.append("DEEPSEEK_API_KEY が無い → 要約なしモードで動作")

    return cfg
