# mainichi-news (毎日ニュース)

AI が毎朝、**島根県のローカルニュース**を要約してメールで届ける個人用ダイジェスト。

- **実行**: 毎朝 06:00、または PC を起動したとき（1 日 1 回だけ / 同日 2 回目はスキップ）
- **OS**: Linux (systemd user timer) / macOS (launchd LaunchAgent)
- **ソース**: Google News RSS（島根・松江）+ Yahoo!ニュース 地域 RSS。API キー不要
- **要約**: DeepSeek (`deepseek-chat`, OpenAI 互換 API)
- **配信**: メール（HTML + テキスト）。未設定なら `digest/` に保存のみ
- **アーカイブ**: `digest/YYYY-MM-DD.md` を git commit & push
- **依存**: Python 3.13 のみ（サードパーティ製ランタイム依存ゼロ）

## クイックスタート

```bash
uv sync                       # .venv 作成 + インストール
cp config.example.toml config.toml
mkdir -p ~/.config/mainichi-news
cp .env.example ~/.config/mainichi-news/.env
chmod 600 ~/.config/mainichi-news/.env
$EDITOR ~/.config/mainichi-news/.env   # DeepSeek キー + SMTP

uv run mainichi-news status    # 設定確認
uv run mainichi-news preview   # メール送らず Markdown を表示
uv run mainichi-news run       # 今日の分を実行（同日 2 回目は no-op）
```

## コマンド

| コマンド | 動作 |
|---|---|
| `run` | 今日の分を実行。配信済みなら何もせず exit 0（冪等ガード） |
| `run --force` | 同日でも再実行 |
| `force` | `run --force` と同じ。`--no-email` でメールだけ抑止 |
| `preview` | メール送信・state 更新・アーカイブなしで Markdown を stdout に出力 |
| `status` | 設定 / API キー / メール / 最終実行日を表示 |
| `install` | systemd timer または launchd LaunchAgent を配置して有効化 |
| `install --no-enable` | ファイル配置のみ（有効化しない） |
| `uninstall` | 登録解除 |

`preview --date 2026-11-18` で日付指定も可能。

## 設定

秘匿でない設定は `config.toml`（`config.example.toml` を参照）。
秘匿値は `~/.config/mainichi-news/.env`（プロセスの環境変数が優先）。

探索順:

```
config: --config > $MAINICHI_NEWS_CONFIG > ./config.toml > ~/.config/mainichi-news/config.toml
env   : --env    > $MAINICHI_NEWS_ENV    > ~/.config/mainichi-news/.env
```

主な項目:

| セクション | キー | 既定 |
|---|---|---|
| `[source]` | `queries` | `["島根", "松江"]` |
| | `window_hours` | `30`（これより古い記事は捨てる） |
| | `max_articles` | `30` |
| | `yahoo` | `true`（Yahoo 地域 RSS を補助利用） |
| `[summarize]` | `model` / `top_n` / `others_n` | `deepseek-chat` / `3` / `8` |
| `[deliver]` | `to` / `from` / `subject_prefix` | 空 / 空 / `【毎日ニュース】` |
| `[archive]` | `enabled` / `push` | `true` / `true` |

環境変数: `DEEPSEEK_API_KEY`, `SMTP_HOST`, `SMTP_PORT` (587/465), `SMTP_STARTTLS`,
`SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `MAINICHI_NEWS_TO`。
Gmail はアプリパスワードを使う（2 段階認証を有効化 → アプリパスワード発行）。

## スケジューリング

判定ロジックは Python 側にあり、トリガーは「きっかけ」でしかない。

```
$XDG_STATE_HOME/mainichi-news/last-run   # 例: 2026-11-18 + 実行メタデータ
→ 今日の日付と一致したら exit 0（何もせず終了）
→ 配信成功時のみ書き込む（失敗時は書かない = 次回トリガーで再試行）
```

そのため、06:00 タイマーと起動時トリガーを両方仕掛けても二重配信は起きない。

### Linux

```bash
uv run mainichi-news install
systemctl --user list-timers mainichi-news.timer
journalctl --user -u mainichi-news.service -n 50   # ログ
```

`OnCalendar=*-*-* 06:00:00` + `OnBootSec=90s` + `Persistent=true`（逃した分を補完）。

### macOS

```bash
uv run mainichi-news install
launchctl print gui/$(id -u)/dev.kakkoi.mainichi-news | head
tail -f ~/Library/Logs/mainichi-news.log
```

`RunAtLoad`（ログイン時）+ `StartCalendarInterval`（06:00）。guard が同日 2 回目を弾く。

## 仕組み

```
Google News RSS ─┐
                 ├→ 重複除去/正規化 → DeepSeek(JSON) → Markdown+HTML ─┬→ digest/*.md
Yahoo 地域 RSS ──┘        （島根フィルタ）        （失敗時は見出しのみ） ├→ メール (SMTP)
                                                                      └→ git commit/push
```

- 記事は LLM に**番号付き**で渡し、LLM は番号で選ぶ。URL は元記事から機械的に付与するので
  ハルシネーション URL が混ざらない。
- DeepSeek 失敗（キー無効・タイムアウト・JSON 崩れ）時は 1 回リトライ →
  それでもだめなら「要約なしヘッドライン」モードで配信（無音で落とさない）。
- Google News の `description` はタイトル＋媒体名のみなので本文要約には使わない
  （要約はタイトル + 媒体名 + 日時から生成）。

## 構成

```
src/mainichi_news/
├── cli.py            # run / force / preview / status / install / uninstall
├── pipeline.py       # collect → summarize → render → deliver
├── config.py         # config.toml + .env
├── state.py          # 1 日 1 回の冪等ガード
├── sources/          # google_news.py, yahoo.py, rss.py
├── dedupe.py         # タイトル正規化・重複除去・時間窓
├── summarize.py      # DeepSeek（JSON, id 参照, フォールバック）
├── format.py         # Markdown / HTML
├── deliver/          # file.py（常時）, email.py（SMTP）
├── archive.py        # digest を git add/commit/push（失敗しても致命でない）
├── install.py        # systemd / launchd 登録
└── templates/        # unit / plist テンプレート
tests/                # pytest（ネットワーク不要）
```

## 開発

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
```

テストはネットワークと API キー不要。実 RSS の疎通確認は `preview` で行う。

## ドキュメント

- [docs/PLAN.md](docs/PLAN.md) — 設計判断・ソース検証結果・実装状況
