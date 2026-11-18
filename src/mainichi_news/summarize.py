"""Summarisation via DeepSeek (OpenAI-compatible chat completions)."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import date

from .config import Config
from .models import Article, Digest, Story

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """あなたは島根県のローカルニュースを毎朝1通にまとめる編集者です。
与えられた記事一覧だけを根拠に、日本語で簡潔なダイジェストを作ります。
推測や記事に無い事実は書かない。記事は番号(id)で参照する。
出力は JSON オブジェクトのみ（前後に説明文やコードフェンスを付けない）。"""

USER_TEMPLATE = """今日は {day} です。以下の島根県関連の記事から、朝刊ダイジェストを作ってください。

# 記事一覧
{articles}

# 出力ルール
- one_liner: 今日の島根を一言で表す20〜40字の文。
- top: 重要な {top_n} 本。選定優先度 = 県政/行政 > 事件事故 > 経済/雇用 > 交通/インフラ > 生活/イベント。
  各要素は {{"id": 記事番号, "summary": "2〜3文の要約", "why": "なぜ重要か1文"}}。
- others: 残りから {others_n} 件。各要素は {{"id": 記事番号, "summary": "1文の要約"}}。
- numbers: 本文中に示された数字・トレンドを最大3件、1行ずつ。無ければ空配列。
- id は必ず上の記事一覧の番号を使う。同じ id を2回使わない。
- 出力形式: {{"one_liner": str, "top": [...], "others": [...], "numbers": [str]}}"""


class SummarizeError(RuntimeError):
    """Raised when the LLM call fails."""


def build_user_prompt(articles: list[Article], cfg: Config, day: date) -> str:
    lines: list[str] = []
    for index, article in enumerate(articles, start=1):
        published = article.published.strftime("%m/%d %H:%M") if article.published else "?"
        body = article.summary[: cfg.summarize.max_body_chars]
        lines.append(
            f"{index}. [{article.source}] {article.title} ({published})\n   {body}"
        )
    return USER_TEMPLATE.format(
        day=day.strftime("%Y-%m-%d"),
        articles="\n".join(lines),
        top_n=cfg.summarize.top_n,
        others_n=cfg.summarize.others_n,
    )


def post_chat(cfg: Config, payload: dict) -> dict:
    url = f"{cfg.summarize.base_url}/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
            "User-Agent": "mainichi-news/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=cfg.summarize.timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:500].decode("utf-8", "replace")
        raise SummarizeError(f"API {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SummarizeError(f"API 接続失敗: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SummarizeError(f"API 応答が JSON でない: {raw[:200]!r}") from exc


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(response: dict) -> dict:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SummarizeError(f"応答に choices が無い: {str(response)[:200]}") from exc
    text = _FENCE_RE.sub("", (content or "").strip()).strip()
    if not text:
        raise SummarizeError("要約結果が空")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise SummarizeError(f"要約 JSON を抽出できない: {text[:200]}") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise SummarizeError(f"要約 JSON が壊れている: {exc}") from exc
    if not isinstance(data, dict):
        raise SummarizeError("要約 JSON がオブジェクトでない")
    return data


def _story_for(article: Article, summary: str, why: str = "") -> Story:
    return Story(
        title=article.title,
        summary=summary.strip(),
        why=why.strip(),
        url=article.url,
        source=article.source,
    )


def to_digest(
    data: dict, articles: list[Article], day: date, cfg: Config
) -> Digest:
    """Attach real URLs/sources from the article list to the LLM's picks."""

    def pick(entry: object) -> Article | None:
        if not isinstance(entry, dict):
            return None
        try:
            index = int(entry.get("id")) - 1
        except (TypeError, ValueError):
            return None
        if 0 <= index < len(articles):
            return articles[index]
        return None

    digest = Digest(day=day, article_count=len(articles))
    digest.one_liner = str(data.get("one_liner", "")).strip()[:120]

    used: set[int] = set()
    for entry in data.get("top") or []:
        article = pick(entry)
        if article is None or id(article) in used:
            continue
        used.add(id(article))
        digest.top.append(
            _story_for(
                article,
                str(entry.get("summary", "")),
                str(entry.get("why", "")),
            )
        )
        if len(digest.top) >= cfg.summarize.top_n:
            break

    for entry in data.get("others") or []:
        article = pick(entry)
        if article is None or id(article) in used:
            continue
        used.add(id(article))
        digest.others.append(_story_for(article, str(entry.get("summary", ""))))
        if len(digest.others) >= cfg.summarize.others_n:
            break

    numbers = data.get("numbers") or []
    if isinstance(numbers, list):
        digest.numbers = [str(n).strip()[:160] for n in numbers if str(n).strip()][:3]
    return digest


def fallback_digest(articles: list[Article], day: date, cfg: Config, reason: str) -> Digest:
    log.warning("要約なしモード: %s", reason)
    digest = Digest(day=day, article_count=len(articles), degraded=True)
    digest.one_liner = "AI要約なし（見出しのみ）"
    for article in articles[: cfg.summarize.top_n]:
        digest.top.append(_story_for(article, article.summary[:180]))
    start = min(len(articles), cfg.summarize.top_n)
    for article in articles[start : start + cfg.summarize.others_n]:
        digest.others.append(_story_for(article, article.summary[:90]))
    return digest


def summarize(articles: list[Article], day: date, cfg: Config) -> Digest:
    if not articles:
        return fallback_digest([], day, cfg, "記事が0件")
    if not cfg.api_key:
        return fallback_digest(articles, day, cfg, "DEEPSEEK_API_KEY 未設定")

    payload = {
        "model": cfg.summarize.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(articles, cfg, day)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": cfg.summarize.temperature,
        "max_tokens": 2000,
        "stream": False,
    }

    last_error = ""
    for attempt in range(cfg.summarize.retries + 1):
        if attempt:
            time.sleep(2 * attempt)
        try:
            data = extract_json(post_chat(cfg, payload))
        except SummarizeError as exc:
            last_error = str(exc)
            log.warning("要約失敗 (%d 回目): %s", attempt + 1, exc)
            continue
        digest = to_digest(data, articles, day, cfg)
        if digest.top:
            return digest
        last_error = "top が空"
        log.warning("要約結果に top が無い")
    return fallback_digest(articles, day, cfg, last_error or "不明")
