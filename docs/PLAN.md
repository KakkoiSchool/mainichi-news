# 実装プラン

最終更新: 2026-11-11

## 0. 決定事項

| 項目 | 決定 |
|------|------|
| 対象 | **島根県のローカルニュースのみ** |
| 要約モデル | **DeepSeek** (`deepseek-chat`, OpenAI 互換 API) |
| 配信 | **メール**（v1）。将来 Telegram / Discord に差し替え可能な設計 |
| フォーマット | **案 B**: 今日の 3 本（各 3 行） + その他の見出し（各 1 行） + 気になる数字 |
| 言語 | **Python 3.13** |
| アーカイブ | `digest/YYYY-MM-DD.md` を GitHub に push（このリポジトリ） |
| 実行 | **毎朝 6:00 または起動時**、1 日 1 回だけ |
| OS | Linux (systemd) / macOS (launchd) 両対応 |

## 1. スケジューリング（クロスプラットフォーム）

**systemd は macOS では動かない。** macOS は `launchd`（LaunchAgent）を使う。
そのためスケジューラは差し替え可能な薄い層にして、判定ロジックは Python 側に置く。

共通ルール:

```
「その日の号」は 06:00 に解禁される
- 06:00 以降に起動した  → すぐ実行
- 06:00 より前に起動    → 06:00 まで待って実行（常駐タイマー）
- 同じ日に 2 回起動     → 2 回目は何もしない（state ガード）
```

判定はすべて `mainichi-news run` の中の **冪等ガード** が行う:

```
$XDG_STATE_HOME/mainichi-news/last-run   # "2026-11-11"
→ 今日の日付と一致したら exit 0（何もせず終了）
→ 実行成功時のみ書き込む（失敗時は書かない = 再試行可能）
```

結果として、トリガーを何個仕掛けても二重配信は起きない。
トリガーは「実行のきっかけ」でしかない。

### Linux — systemd user units

`~/.config/systemd/user/mainichi-news.{service,timer}`

```ini
# mainichi-news.service
[Unit]
Description=Mainichi News daily digest

[Service]
Type=oneshot
ExecStart=%h/.local/bin/mainichi-news run
Environment=PYTHONUNBUFFERED=1
```

```ini
# mainichi-news.timer
[Unit]
Description=Mainichi News at 06:00 and after boot

[Timer]
OnCalendar=*-*-* 06:00:00
OnBootSec=90s
Persistent=true
RandomizedDelaySec=30

[Install]
WantedBy=timers.target
```

- `Persistent=true` … 06:00 に PC が落ちていた場合、次の起動時に補完実行（catch-up）
- `OnBootSec` … 起動 90 秒後にも発火（06:00 以降に起動した日を拾う）
- 二重発火しても state ガードが弾く

### macOS — launchd LaunchAgent

`~/Library/LaunchAgents/dev.kakkoi.mainichi-news.plist`

```
ProgramArguments = [ "<repo>/.venv/bin/mainichi-news", "run" ]
RunAtLoad                = true            # ログイン時（= 起動時）
StartCalendarInterval    = 06:00           # 毎朝 6 時
```

- `RunAtLoad` でログイン時に必ず呼ばれる → guard が同日 2 回目を弾く
- スリープ中に 6:00 を過ぎた場合、macOS は起床時に一度だけ遅延実行する
- launchd は systemd の `Persistent` のような「逃した分の補完」を自動ではしない → `RunAtLoad` + guard でカバー

### Windows（将来）

Task Scheduler の「スタートアップ時」「毎日 6:00」の 2 トリガー + 同じ guard。
`install` サブコマンドで登録スクリプトを出し分ける。

```bash
mainichi-news install     # OS を判定して unit を配置 & enable
mainichi-news uninstall
```

## 2. ソース（島根県のみ）

### 検証結果（2026-11-11 実測）

| 取得元 | 結果 |
|--------|------|
| Google News RSS `q=島根` | **200, 108 件/日**。山陰中央新報・TSK・NKT・NHK 松江・日テレ系を網羅。**API キー不要** |
| Yahoo! ニュース 地域 RSS (`topics/local.xml`) | 200 だが**全国ローカル**。島根フィルタはキーワード頼み |
| Yahoo! メディア RSS (`media/saninchuo.xml` 等) | **404（廃止）** |
| 山陰中央新報 公式 RSS | **存在しない**（`/rss/`, `/feed`, `/feed.xml` すべて 404） |
| NHK 松江 `lnews/rss.xml` | **401** |

→ **v1 の主ソース = Google News RSS**。Yahoo 地域 RSS は補助（島根キーワード一致分のみ採用）。

```
https://news.google.com/rss/search?q=島根&hl=ja&gl=JP&ceid=JP:ja
https://news.google.com/rss/search?q=松江&hl=ja&gl=JP&ceid=JP:ja      # 併用
https://news.yahoo.co.jp/rss/topics/local.xml                          # 補助
```

注意点:
- Google News のアイテム URL は Google 経由のエンコード URL（`news.google.com/rss/articles/CBMi...`）。
  ブラウザで開けば記事へリダイレクトする。v1 はこのまま使用。
  元 URL が必要になったら `batchexecute` でデコード（v1.1 で対応可）
- タイトル末尾に `（山陰中央新報）` 等の媒体名が付くので除去する
- 同一記事が `q=島根` と `q=松江` で重複 → タイトル正規化で重複除去
- 記事本文は 402/有料壁のことがある → 取得できなければ RSS タイトル + 概要だけで要約

将来の候補（v1.1 以降）:
- 島根県公式・各市町村サイト
- 山陰中央新報のスクレイピング（規約確認の上で）
- イベント/交通/気象（JR 西日本, 気象庁 XML）

## 3. 要約（DeepSeek）

- OpenAI 互換 API: `base_url=https://api.deepseek.com`, `model=deepseek-chat`
- 記事を 1 バッチで投入し、JSON で構造化出力
  （`response_format={"type":"json_object"}`）
- 出力スキーマ:

```json
{
  "one_liner": "今日の島根を一言で",
  "top3": [
    {"title": "...", "summary": "2-3文", "why": "なぜ重要か", "url": "...", "source": "山陰中央新報"}
  ],
  "others": [{"title": "...", "summary": "1文", "url": "...", "source": "..."}],
  "numbers": ["数字やトレンド 1 行"]
}
```

- 入力削減: 記事は最大 30 件、本文は先頭 1200 文字
- コスト: 1 回あたり 1 万トークン前後 → **1 日 1 円未満**
- 失敗時: 1 回リトライ → だめなら「要約なしヘッドライン」モードで配信（無音で落とさない）

## 4. 配信（v1 = メール）

- **HTML メール + プレーンテキスト**のマルチパート
- 送信手段は 2 案、実装は `deliver/` の差し替えで吸収:
  - **A: SMTP（推奨）** … Gmail アプリパスワード / さくら等。追加サービス契約不要
  - **B: Resend API** … ドメイン認証が要る。API キー 1 つで楽
- 件名: `【毎日ニュース】11/11(水) 島根 — <one_liner>`
- 送信先: 自分のメールアドレス
- 将来の口: `--deliver telegram|discord|stdout` を後から足せる interface

```
src/mainichi_news/deliver/base.py      # Protocol: send(digest) -> None
src/mainichi_news/deliver/email.py
src/mainichi_news/deliver/file.py      # 常に実行（Markdown 保存）
```

## 5. フォーマット（案 B / 島根版）

```markdown
# 毎日ニュース 2026-11-11 (水) — 島根

> 今日の一言: 松江で〇〇。県内は…

## 今日の 3 本

### 1. 見出し
要約 2〜3 文。
**なぜ重要**: 1 文。
[山陰中央新報](url)

### 2. …
### 3. …

## その他の見出し
- 見出し — 一言要約（山陰中央新報）
- 見出し — 一言要約（TSKさんいん中央テレビ）
- …

## 気になる数字・トレンド
- 〇〇が前年比 +12%
```

- メールはこの Markdown を HTML 化して送る
- 同時に `digest/2026-11-11.md` として保存 → commit & push（公開アーカイブ）
- 「3 本」の選定基準: 県政/行政 > 事件事故 > 経済/雇用 > 交通/インフラ > 生活/イベント

## 6. リポジトリ構成

```
mainichi-news/
├── README.md
├── pyproject.toml            # uv 管理
├── docs/PLAN.md
├── src/mainichi_news/
│   ├── __main__.py           # CLI: run / install / preview / force
│   ├── config.py             # config.toml + .env 読み込み
│   ├── state.py              # last-run 冪等ガード
│   ├── sources/google_news.py
│   ├── sources/yahoo.py
│   ├── dedupe.py
│   ├── summarize.py          # DeepSeek
│   ├── format.py             # Markdown / HTML
│   ├── deliver/{base,email,file}.py
│   └── archive.py            # git add/commit/push digest/
├── digest/2026-11-11.md
├── systemd/mainichi-news.{service,timer}
├── launchd/dev.kakkoi.mainichi-news.plist
├── scripts/install.sh
├── config.example.toml
└── .env.example
```

設定:

```toml
# config.toml（秘匿でない）
[source]
queries = ["島根", "松江"]
max_articles = 30

[summarize]
model = "deepseek-chat"
top_n = 3
others_n = 10

[deliver]
to = "you@example.com"
from = "you@example.com"
subject_prefix = "【毎日ニュース】"
```

```
# ~/.config/mainichi-news/.env   (chmod 600, git 管理外)
DEEPSEEK_API_KEY=sk-...
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
```

## 7. 実装順

1. `sources/google_news.py` — 島根記事取得 + 媒体名除去 + 重複除去
2. `summarize.py` — DeepSeek で JSON 要約
3. `format.py` — Markdown / HTML (メール)
4. `deliver/email.py` — SMTP 送信
5. `state.py` + CLI `run` / `force` / `preview`（メール送らず stdout）
6. `archive.py` — digest を push
7. `install` — systemd / launchd 配置
8. テスト: `preview` で 1 週間運用 → 調整

## 8. 追加で必要な情報

1. **メール**: 受信用アドレスと、送信に使う SMTP（Gmail アプリパスワード？ 独自ドメイン？）
2. **DeepSeek API キー**: 有効なものを持っているか
3. **OS**: 実際に毎日動かすのは Linux（今の Ubuntu）か Mac か。両方なら両方 install
4. **記事数**: 3 本 + 10 件で足りるか（島根ローカルは日によって少ないので 3 + 5 くらいが妥当かも）
