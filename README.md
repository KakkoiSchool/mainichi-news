# mainichi-news (毎日ニュース)

AI が毎朝、**島根県のローカルニュース**を要約してメールで届ける個人用ダイジェスト。

- **実行**: 毎朝 06:00、または PC を起動したとき（1 日 1 回だけ / 同日 2 回目はスキップ）
- **OS**: Linux (systemd timer) / macOS (launchd LaunchAgent)
- **ソース**: Google News RSS（島根・松江）+ Yahoo!ニュース 地域 RSS。API キー不要
- **要約**: DeepSeek (`deepseek-chat`)
- **配信**: メール（HTML + テキスト）
- **アーカイブ**: `digest/YYYY-MM-DD.md`

## ドキュメント

- [docs/PLAN.md](docs/PLAN.md) — 実装プラン（決定事項・スケジューリング・ソース検証結果）

## 使い方（予定）

```bash
uv sync
cp .env.example ~/.config/mainichi-news/.env    # キーを書く
uv run mainichi-news preview    # メール送らずに Markdown を出力
uv run mainichi-news run        # 今日の分を実行（同日 2 回目は no-op）
uv run mainichi-news install    # systemd / launchd に登録
```
