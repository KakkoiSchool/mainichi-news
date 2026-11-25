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
| `install` | systemd timer / launchd LaunchAgent / Task Scheduler に登録 |
| `install --no-enable` | ファイル配置のみ（有効化しない） |
| `install --print` | 書き込まず scheduler ファイルを表示（`--platform` 指定可） |
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

> **注意**: `.env` は `config.toml` と違い `./.env` を自動では読まない。
> リポジトリ内の `.env` を編集しても効かないので、どちらか一方に統一する。
>
> ```bash
> ln -sf "$PWD/.env" ~/.config/mainichi-news/.env   # リポジトリ側を正にする
> # もしくは: uv run mainichi-news --env .env force  （--env はサブコマンドより前）
> ```

## メール送信の設定

`SMTP_HOST` と送信先（`MAINICHI_NEWS_TO` か `[deliver].to`）の両方が揃ったときだけ送信する。
どちらかが空だと「保存のみ」で静かにスキップするので、まず `status` で確認する。

```bash
uv run mainichi-news status    # email : you@example.com via smtp.example.com:587 なら OK
uv run mainichi-news -v force  # 送信まで込みで実行（-v で SMTP のログ）
```

### Gmail（アプリパスワード）

1. <https://myaccount.google.com/security> で **2 段階認証** を有効化（必須）
2. <https://myaccount.google.com/apppasswords> でアプリ名 `mainichi-news` を作成
3. 表示された **16 文字** を `SMTP_PASSWORD` に入れる（空白は詰める）

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USER=you@gmail.com
SMTP_PASSWORD=abcdefghijklmnop     # 16 文字のアプリパスワード（アカウントのパスワードではない）
SMTP_FROM=you@gmail.com
MAINICHI_NEWS_TO=you@gmail.com
```

Google が SPF/DKIM を整えてくれるので、独自ドメインの DNS を触らずに済む最短ルート。
送信控えは Gmail の「送信済み」に残る（そこに出ていなければ SMTP 側で受理されていない）。

### Brevo（SMTP リレー）

1. **送信元を認証**: Brevo → *Senders, Domains & Dedicated IPs* → *Senders* → アドレス追加 →
   届いた確認リンクをクリック。未認証の `SMTP_FROM` は `550 Sender not verified` で拒否される。
2. **SMTP 認証情報**: Brevo → *SMTP & API* → **SMTP** タブ
   - host: `smtp-relay.brevo.com` / port: `587`（STARTTLS）または `465`（SSL）、`2525` も可
   - **Login**: 画面に出ている値をそのまま使う（新しいアカウントは `9xxxxx001@smtp-brevo.com` 形式）
   - **SMTP key**: `xsmtpsib-…`。表示されていなければ発行する。**アカウントのパスワードではない**

```bash
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USER=9xxxxx001@smtp-brevo.com  # SMTP タブの Login（ログインメールとは限らない）
SMTP_PASSWORD=xsmtpsib-xxxxxxxx      # SMTP key
SMTP_FROM=contact@yourdomain.com     # Brevo で認証した送信元
MAINICHI_NEWS_TO=you@example.com
```

#### 独自ドメインを使う場合（重要）

独自ドメインを送信元に使うときは、Brevo のドメイン設定画面に表示された DNS レコードを使う。

1. Brevo の画面で送信ドメインを追加する。
2. 指示された所有確認、DKIM、DMARC のレコードを DNS に反映する。既存の DMARC レコードがある場合は、現在のポリシーを確認して既存レコードを編集する。
3. Brevo でドメイン認証が完了したことを確認し、自分のアドレスへテスト送信する。受信メールのヘッダーで DKIM と DMARC の結果を確認する。

通常のドメイン認証では SPF と MX の追加は不要。専用 IP を設定する場合は、Brevo がその設定用に指定するレコードに従う。[Brevo 公式のドメイン認証手順](https://help.brevo.com/hc/en-us/articles/12163873383186-Authenticate-your-domain-with-Brevo-Brevo-code-DKIM-DMARC)。

### うまく届かないとき

| 症状 | 原因 / 対処 |
|---|---|
| `メール未設定のため送信スキップ` | `SMTP_HOST` か送信先が空。`status` で確認 |
| `SMTP_USER / SMTP_PASSWORD が未設定` | `.env` が空 or 別ファイルを編集している（`--env` / symlink で統一） |
| `535 Authentication failed` | Login かパスワード違い（Gmail はアプリパスワード、Brevo は SMTP key） |
| `550 Sender not verified` | `SMTP_FROM` が Brevo 未認証 / Gmail 以外のドメインを勝手に From にしている |
| `Connection unexpectedly closed` | port と TLS の不一致（465 は SSL、587 は STARTTLS） |
| ログは成功なのに届かない | Gmail の迷惑メール / Brevo の *Transactional → Logs* を確認。独自ドメインなら DKIM 未設定を疑う |

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

### Windows

```powershell
uv run mainichi-news install
schtasks /Query /TN mainichi-news /V /FO LIST
```

ログオン 90 秒後 + 毎日 06:00 の 2 トリガー。`StartWhenAvailable` で逃した回を補完。
実行はログオン中のみ（`LogonType=InteractiveToken`、パスワード不要）。

### macOS

```bash
uv run mainichi-news install
launchctl print gui/$(id -u)/dev.kakkoi.mainichi-news | head
tail -f ~/Library/Logs/mainichi-news.log
```

`RunAtLoad`（ログイン時）+ `StartCalendarInterval`（06:00）。guard が同日 2 回目を弾く。

### 3 OS の scheduler ファイルを今の OS で確認

```bash
uv run mainichi-news install --print --platform linux
uv run mainichi-news install --print --platform macos
uv run mainichi-news install --print --platform windows
```

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
uv run ruff check src tests scripts
```

テストはネットワークと API キー不要。実 RSS の疎通確認は `preview` で行う。

### 実発火テスト（OS スケジューラを実際に動かす）

```bash
uv run python scripts/firing_test.py --mode fire          # マーカーを数秒後に発火
uv run python scripts/firing_test.py --mode digest --yes  # run を scheduler 経由で実行 + 冪等ガード
```

- `fire`: systemd transient timer / launchd `StartInterval` / `schtasks /SC ONCE` を実登録し、
  マーカーファイルが書かれたことを確認（ネットワーク不要）
- `digest`: 一時 config/state で `mainichi-news run` を scheduler 経由実行 → `digest/*.md` 生成、
  2 回目発火で state 不変（二重配信なし）を確認
- スケジューラが使えない環境は exit 77（skip）

3 OS の scheduler ファイル自体は `tests/test_schedulers.py` が全 OS 分をパース検証する
（systemd unit / plist / Task Scheduler XML）。CI は ubuntu / macos / windows の matrix で
両方を実行する。

## ドキュメント

- [docs/PLAN.md](docs/PLAN.md) — 設計判断・ソース検証結果・実装状況
