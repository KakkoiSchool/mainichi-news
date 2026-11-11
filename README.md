# mainichi-news (毎日ニュース)

AI が毎朝ニュースを要約して届ける個人用ダイジェスト。

- **起動**: PC を立ち上げた日に 1 回だけ自動実行（同日 2 回目はスキップ）
- **ソース**: Yahoo!ニュース（RSS、API キー不要）
- **要約**: LLM API
- **配信**: 未定（[docs/PLAN.md](docs/PLAN.md) 参照）
- **アーカイブ**: `digest/YYYY-MM-DD.md`

## Status

計画中。実装方針は [docs/PLAN.md](docs/PLAN.md)。

## 手動実行（予定）

```bash
./run.sh            # 今日の分が無ければ実行
./run.sh --force    # 強制再生成
```
