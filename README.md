Slack Workspace Relationship Graph

概要
- Slackの全チャンネル（現在ユーザーがアクセス可能な範囲）からメッセージを収集し、ユーザ間の関係（メンション、返信、リアクション）をグラフ化します。
- PythonのCLIで「取得→構築→出力」を段階的に実行します。

特徴（初期スケルトン）
- 取得層は差し替え可能（Webクライアント API / 公式 Web API）。
- 軽量なSQLiteを採用（ローカル・個人利用向け）。
- NetworkXでグラフ生成、GraphML/GEXF出力。yfiles-jupyter-graphs等での可視化を想定。
- GraphMLノード属性にユーザー情報を含めます（`label`, `username`, `name`, `real_name`）。

クイックスタート
1) `python -m venv .venv && source .venv/bin/activate`
2) `pip install -r requirements.txt`
3) SlackのWebクライアントで `scripts/slack_capture.js` をコンソール実行し、NDJSONをダウンロード。
   - 詳細手順: `docs/slack_capture.md`
4) NDJSON取り込み: `python -m slack_graph import-ndjson path/to/capture.ndjson`
5) グラフ生成・出力: `python -m slack_graph build`

出力されるGraphMLのノード属性
- `label`: 表示名優先（なければ `real_name` → `username` → `id`）
- `username`: ハンドル名（存在する場合）
- `name`: display_name（存在する場合）
- `real_name`: 本名（存在する場合）

注意事項
- キャプチャスクリプトはセキュリティ対策済み（トークン自動マスク、機微ヘッダー除外）ですが、出力ファイルの取り扱いには引き続き注意してください。
- ネットワークアクセスを伴うAPI取得機能は削除し、Webクライアントのログ取り込みに一本化しています。

構成
- `src/slack_graph/` モジュール群
- `docs/spec/` 設計書
- `data/` SQLite DB（自動作成）
- `output/` グラフファイル（GraphML/GEXF）

Webクライアントからの記録（コンソール実行）
- SlackのWebページ上で動作しているAPI呼び出し（`/api/*`）を横取り・記録するスニペットを用意しています。
- ブラウザの開発者ツール Console に `scripts/slack_capture.js` を貼り付けて実行してください。

slack_capture.js の主要API:
```javascript
// ステータス確認（ログ数、ユーザー数、メモリ使用量）
_slackCapture.status()

// 設定変更（デバッグログ有効化、ログ上限変更など）
_slackCapture.setConfig({ verbose: true, maxLogSize: 5000 })

// APIログをNDJSONでダウンロード
_slackCapture.download()

// ユーザー収集モードを有効化（APIレスポンスからユーザー情報を自動抽出）
_slackCapture.enableUserCapture()

// 収集したユーザー情報をダウンロード
_slackCapture.downloadUsers()

// キャプチャ停止（fetch/XHRフックを解除）
_slackCapture.stop()
```

- 詳細な使い方は `docs/slack_capture.md` を参照。
