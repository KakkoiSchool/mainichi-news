"""Pipeline: collect → dedupe → summarise → render → deliver."""

from __future__ import annotations

import logging
from datetime import date

from . import format as fmt
from . import state
from .config import Config, ConfigError
from .dedupe import dedupe, within_window
from .deliver.email import EmailDeliverer
from .deliver.file import FileDeliverer
from .models import Article, Digest
from .sources import google_news, yahoo
from .summarize import summarize

log = logging.getLogger(__name__)


def collect(cfg: Config) -> list[Article]:
    articles = google_news.fetch_articles(cfg.source, log=log)
    log.info("google-news: %d 件", len(articles))
    if cfg.source.yahoo_enabled:
        extra = yahoo.fetch_articles(cfg.source, log=log)
        log.info("yahoo: %d 件 (島根フィルタ後)", len(extra))
        articles.extend(extra)
    articles = within_window(articles, cfg.source.window_hours)
    articles = dedupe(articles)
    articles.sort(
        key=lambda a: a.published.timestamp() if a.published else 0.0, reverse=True
    )
    articles = articles[: cfg.source.max_articles]
    log.info("重複除去後: %d 件", len(articles))
    return articles


def build_digest(cfg: Config, day: date) -> Digest:
    articles = collect(cfg)
    return summarize(articles, day, cfg)


def deliver(
    cfg: Config, digest: Digest, markdown: str, html: str, *, email: bool = True
) -> str:
    """Deliver to file (always) and email (if configured). Returns a summary."""
    delivered = [FileDeliverer(cfg.digest_dir).send(digest, digest.subject, markdown, html)]
    if email:
        sender = EmailDeliverer(cfg)
        if sender.enabled:
            delivered.append(sender.send(digest, digest.subject, markdown, html))
        else:
            log.info("メール未設定のため送信スキップ（保存のみ）")
    return ",".join(delivered)


def run_once(
    cfg: Config,
    day: date | None = None,
    *,
    force: bool = False,
    email: bool = True,
) -> int:
    """Run the daily job once. Returns a process exit code."""
    day = day or date.today()
    if not force and state.is_done(day):
        log.info("%s は配信済み。何もしない (%s)", day, state.last_run_path())
        return 0

    try:
        digest = build_digest(cfg, day)
    except ConfigError:
        raise
    except Exception as exc:  # noqa: BLE001 - manual run should still report the cause
        log.error("ダイジェスト生成に失敗: %s", exc)
        return 1

    if not digest.all_stories:
        log.warning("記事が見つからないため配信しない（state は更新しない）")
        return 1

    markdown = fmt.render_markdown(digest)
    html = fmt.render_html(digest)

    try:
        delivered = deliver(cfg, digest, markdown, html, email=email)
    except ConfigError as exc:
        log.error("%s", exc)
        log.error("配信失敗。state を更新しないので次回再試行する")
        return 1

    state.mark_done(day, articles=digest.article_count, delivered=delivered)
    log.info("配信完了: %s", delivered)

    if cfg.archive.enabled:
        from .archive import archive_digest

        archive_digest(cfg, day)
    return 0
