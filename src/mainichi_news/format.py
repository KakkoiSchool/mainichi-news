"""Render a Digest as Markdown and HTML (email)."""

from __future__ import annotations

import html

from .models import Digest

WEEKDAYS = "月火水木金土日"


def date_label(day) -> str:
    return f"{day.isoformat()} ({WEEKDAYS[day.weekday()]})"


def render_markdown(digest: Digest) -> str:
    lines = [f"# 毎日ニュース {date_label(digest.day)} — 島根", ""]
    if digest.one_liner:
        lines += [f"> 今日の一言: {digest.one_liner}", ""]
    if digest.degraded:
        lines += ["> ⚠️ AI要約なし（見出しのみ）。後で再実行するか、手動で確認してください。", ""]

    if digest.top:
        lines += ["## 今日の 3 本" if len(digest.top) == 3 else "## 今日の注目", ""]
        for index, story in enumerate(digest.top, start=1):
            lines.append(f"### {index}. {story.title}")
            if story.summary:
                lines += ["", story.summary]
            if story.why:
                lines += ["", f"**なぜ重要**: {story.why}"]
            lines.append("")
            if story.url:
                label = story.source or "記事"
                lines.append(f"[{label}]({story.url})")
            lines.append("")

    if digest.others:
        lines += ["## その他の見出し", ""]
        for story in digest.others:
            summary = f" — {story.summary}" if story.summary else ""
            source = f"（{story.source}）" if story.source else ""
            if story.url:
                lines.append(f"- [{story.title}]({story.url}){summary}{source}")
            else:
                lines.append(f"- {story.title}{summary}{source}")
        lines.append("")

    if digest.numbers:
        lines += ["## 気になる数字・トレンド", ""]
        lines += [f"- {n}" for n in digest.numbers]
        lines.append("")

    lines += ["---", f"記事 {digest.article_count} 件から作成 / mainichi-news", ""]
    return "\n".join(lines)


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def render_html(digest: Digest) -> str:
    parts: list[str] = [
        (
            '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Hiragino Sans\','
            '\'Noto Sans JP\',sans-serif;max-width:640px;margin:0 auto;color:#1a1a1a;'
            'line-height:1.7;font-size:15px;">'
        ),
        (
            '<h1 style="font-size:20px;border-bottom:2px solid #333;padding-bottom:8px;">'
            f"毎日ニュース {_esc(date_label(digest.day))} — 島根</h1>"
        ),
    ]
    if digest.one_liner:
        parts.append(
            '<p style="background:#f4f6f8;border-left:4px solid #4a7dbd;'
            f'padding:10px 14px;margin:16px 0;">{_esc(digest.one_liner)}</p>'
        )
    if digest.degraded:
        parts.append(
            '<p style="color:#a15c00;background:#fff6e5;padding:10px 14px;">'
            "⚠️ AI要約なし（見出しのみ）。後で再実行してください。</p>"
        )

    if digest.top:
        heading = "今日の 3 本" if len(digest.top) == 3 else "今日の注目"
        parts.append(f'<h2 style="font-size:17px;margin-top:28px;">{heading}</h2>')
        for index, story in enumerate(digest.top, start=1):
            parts.append(
                '<div style="margin:0 0 24px 0;padding-bottom:16px;'
                'border-bottom:1px solid #e5e5e5;">'
            )
            title = _esc(story.title)
            if story.url:
                title = (
                    f'<a href="{_esc(story.url)}" style="color:#0b57d0;'
                    f'text-decoration:none;">{title}</a>'
                )
            parts.append(f'<h3 style="font-size:16px;margin:0 0 8px 0;">{index}. {title}</h3>')
            if story.summary:
                parts.append(f"<p style=\"margin:0 0 8px 0;\">{_esc(story.summary)}</p>")
            if story.why:
                parts.append(
                    '<p style="margin:0 0 8px 0;color:#444;">'
                    f"<strong>なぜ重要</strong>: {_esc(story.why)}</p>"
                )
            if story.source:
                parts.append(
                    f'<p style="margin:0;font-size:12px;color:#777;">{_esc(story.source)}</p>'
                )
            parts.append("</div>")

    if digest.others:
        parts.append('<h2 style="font-size:17px;margin-top:28px;">その他の見出し</h2>')
        parts.append('<ul style="padding-left:20px;margin:0;">')
        for story in digest.others:
            title = _esc(story.title)
            if story.url:
                title = f'<a href="{_esc(story.url)}" style="color:#0b57d0;">{title}</a>'
            summary = f' — <span style="color:#444;">{_esc(story.summary)}</span>' if story.summary else ""
            source = f' <span style="color:#888;font-size:12px;">（{_esc(story.source)}）</span>' if story.source else ""
            parts.append(f'<li style="margin:0 0 6px 0;">{title}{summary}{source}</li>')
        parts.append("</ul>")

    if digest.numbers:
        parts.append('<h2 style="font-size:17px;margin-top:28px;">気になる数字・トレンド</h2>')
        parts.append('<ul style="padding-left:20px;margin:0;">')
        parts += [f"<li>{_esc(n)}</li>" for n in digest.numbers]
        parts.append("</ul>")

    parts.append(
        '<p style="margin-top:32px;padding-top:12px;border-top:1px solid #e5e5e5;'
        'font-size:12px;color:#888;">'
        f"記事 {digest.article_count} 件から作成 / mainichi-news</p>"
    )
    parts.append("</div>")
    return "\n".join(parts)
