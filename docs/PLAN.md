# 実装プラン

## 1. 全体フロー

```
boot
 └─ systemd user timer (Persistent=true)
      └─ mainichi-news.service
           ├─ 0) 同日実行チェック (state/last-run)   ← 冪等ガード
           ├─ 1) ネット疎通待ち (リトライ)
           ├─ 2) Yahoo!ニュース RSS 取得
           ├─ 3) 重複除去 + 重要度スコアリング
           ├─ 4) LLM で要約 (JSON で構造化出力)
           ├─ 5) Markdown 整形 → digest/YYYY-MM-DD.md
           ├─ 6) 配信 (Telegram / Discord / メール ...)
           └─ 7) commit & push (アーカイブ)
```

失敗時の扱い: どのステップで落ちても `last-run` は書かない（= 再起動 or 手動で再試行可能）。
無限リトライはしない。最大 2 回まで、その後は通知だけ送る。

## 2. 起動トリガ（1 日 1 回）

要件: 「PC を起動した日に 1 回。同じ日に 2 回起動しても再実行しない」

- **systemd user timer**
  - `OnBootSec=2min` + `OnCalendar=daily` + `Persistent=true`
  - `Persistent=true` → その日分を逃していたら起動時に補完実行
  - Boot 後 2 分待つのは、ネットワーク確立と通知デーモン待ちのため
- **冪等ガード（本命）**
  - `~/.local/state/mainichi-news/last-run` に `2025-11-12` を書く
  - 起動時に日付一致なら即 exit 0
  - timer の挙動が変わっても二重配信しない
- 補足: 深夜 0 時をまたいで起動しっぱなしの場合はその日走らない（仕様として許容）
  - 厳密にやるなら `OnCalendar=*-*-* 06:00:00` も併記 → その場合は「1 日 1 回」で OK

代替案（採らない想定）:
- `~/.config/autostart/*.desktop` … ログイン時のみ、Persistent 無し、冪等管理が面倒
- cron `@reboot` … 同じく Persistent 無し
- GitHub Actions cron … PC 起動トリガにできない。ただし「PC 落ちてても配信される」利点あり → 将来オプション

## 3. ソース

第一候補: **Yahoo!ニュース RSS**（API キー不要、無料、安定）

```
https://news.yahoo.co.jp/rss/topics/top-picks.xml   主要
https://news.yahoo.co.jp/rss/topics/domestic.xml    国内
https://news.yahoo.co.jp/rss/topics/world.xml       国際
https://news.yahoo.co.jp/rss/topics/business.xml    経済
https://news.yahoo.co.jp/rss/topics/it.xml          IT
https://news.yahoo.co.jp/rss/topics/science.xml     科学
https://news.yahoo.co.jp/rss/topics/entertainment.xml エンタメ
https://news.yahoo.co.jp/rss/topics/sports.xml      スポーツ
```

- RSS には本文が無い → 記事ページを取得して本文抽出（`@mozilla/readability` / `trafilatura`）
- ただし Yahoo 記事は転載元サイトへ飛ぶ場合あり。本文取得は「上位 N 件のみ」に絞って負荷と規約リスクを下げる
- 記事本文が取れない場合は RSS の description だけで要約

API キーが必要になるのは **要約 LLM 側** だけ（Yahoo 側は不要）。
将来の追加ソース: NHK RSS, 共同通信, Google News RSS（日本語）, はてブ IT。

## 4. 要約

- 記事ごとに `{title, summary(2-3文), category, importance(1-5), tags[]}` を JSON で出力
- 全体のダイジェストも LLM に書かせる（「今日の3本」の選定込み）
- 入力トークン削減: 本文は先頭 1500 文字まで / 記事数 20-30 件 / 1 回の呼び出しにまとめる（バッチ）
- 候補: `claude-haiku-4.5`, `gemini-2.5-flash`, `gpt-5-mini`
- コスト目安: 1 日 1 回・1 万トークン前後 → 月数十円

## 5. 配信（要決定）

| 案 | 長所 | 短所 |
|----|------|------|
| **Telegram bot** | スマホで読みやすい。無料。長文分割可。Bot API は簡単 | アカウント作成必要。4096 字制限 |
| **Discord webhook** | URL を貼るだけ。無料。即導入 | 個人 DM には向かない（自分のサーバー必要） |
| **メール (SMTP/Resend)** | 見出しだけでも読める。アーカイブ性◎ | 設定が一番面倒 |
| **Slack webhook** | 導入簡単 | 個人用途には過剰 |
| **ローカルのみ** | キー不要。`digest/*.md` + 通知 | 外出先で読めない |

推奨: **Markdown アーカイブ（必須・常時） + Telegram か Discord のどちらか**。
Markdown は repo に push すれば GitHub 上でスマホからも読める（実質無料の配信）。

## 6. フォーマット（要決定）

案 A: フラットな見出しリスト（10-15 件、各 1 行）
案 B: **今日の 3 本（各 3 行） + その他 10 件（各 1 行）** ← 推奨
案 C: カテゴリ別セクション（国内/国際/経済/IT…）各 2-3 件
案 D: 新聞 1 面風（ヘッドライン → 要点 → 気になる話題 → 数字）

案 B の形:

```markdown
# 毎日ニュース 2025-11-12 (水)

> 今日の一言: （LLM が 1 行で全体を総括）

## 今日の 3 本
### 1. 見出し
2-3 文の要約。なぜ重要か 1 文。
[Yahoo!ニュース](url) · 国内

### 2. ...
### 3. ...

## その他の見出し
- 見出し — 一言要約
- ...

## 気になる数字・トレンド
- ...
```

## 7. リポジトリ構成（案）

```
mainichi-news/
├── README.md
├── docs/PLAN.md
├── package.json          # or pyproject.toml
├── src/
│   ├── index.ts          # オーケストレータ
│   ├── state.ts          # last-run 冪等ガード
│   ├── sources/yahoo.ts  # RSS + 本文抽出
│   ├── summarize.ts      # LLM
│   ├── format.ts         # Markdown
│   └── deliver/{telegram,stdout,file}.ts
├── digest/YYYY-MM-DD.md
├── systemd/
│   ├── mainichi-news.service
│   └── mainichi-news.timer
├── scripts/install.sh    # systemd unit を ~/.config/systemd/user に配置
└── config.example.toml
```

設定と秘匿情報:
- `config.toml`（非秘匿: 記事数, カテゴリ, 配信先種別, タイムゾーン）
- `~/.config/mainichi-news/.env`（秘匿: LLM key, webhook URL, SMTP）chmod 600、`.gitignore`

## 8. 決定待ち

1. 配信先: Telegram / Discord / メール / ローカルのみ
2. LLM: どのプロバイダ（キーは既に持っているか）
3. 分量: 3 本 + 10 件で足りるか / 増やすか
4. 実装言語: TypeScript (Node 24) or Python (3.13, uv)
5. `digest/` を public repo に push して良いか（＝ニュース要約が公開される）
6. 実行時刻: 「起動した日 1 回」だけでよいか、それとも毎朝 6:00 固定も併用するか
