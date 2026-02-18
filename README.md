# wise-magpie

Claude Max プランのクォータを最大限に活用するための自律タスク実行ツール。ユーザーの離席中にタスクキューから作業を取り出し、Claude CLI で自動実行する。

## 動機

Claude Max $200 プランは 5 時間ウィンドウごとに約 225 メッセージの制限がある。ユーザーがアクティブでない時間帯のクォータは未使用のまま失われる。wise-magpie はこのアイドル時間を検知し、キューに積まれたタスク（テスト実行、リファクタリング、ドキュメント更新など）を安全に自律実行することでクォータの無駄を減らす。

## 主な機能

- **クォータ自動同期** — Anthropic API からクォータ使用率を自動取得（30 分ごと）。他セッション・他プロジェクトの使用分も含めた正確な値を追跡
- **クォータ追跡** — ウィンドウ内の残り利用可能数を推定し、安全マージンを確保
- **アクティビティ検知** — Claude プロセスの有無でユーザーのアクティブ／アイドルを判定
- **アイドル予測** — 過去の利用パターンから将来のアイドルウィンドウを予測
- **タスクキュー** — 手動追加、TODO コメントスキャン、キューファイル、自動タスク生成の 4 ソースに対応
- **自動タスク生成** — テスト実行・リンター・ドキュメント更新などの定型作業を条件付きで自動キュー投入
- **優先度スコアリング** — ソース種別・キーワード・複雑度に基づく 0〜100 のスコア
- **Git ブランチ隔離** — 各タスクを専用ブランチで実行し、レビュー後にマージ or 破棄
- **予算制御** — タスク単位・日単位の USD 上限でコストを制御

## インストール

```bash
pip install -e ".[dev]"
```

Python 3.10 以上が必要。

## クイックスタート

```bash
# 1. 設定ファイルを生成
wise-magpie config init

# 2. クォータを Anthropic API から自動同期（他プロジェクトの使用分も含む）
wise-magpie quota sync

# 3. タスクを追加
wise-magpie tasks add "Fix authentication bug" -d "Login fails on Safari"

# 4. リポジトリをスキャンして TODO/キューファイルからタスクを取り込み
wise-magpie tasks scan --path .

# 5. タスクキューを確認
wise-magpie tasks list

# 6. デーモンを起動（アイドル時に自動実行開始・クォータは30分ごとに自動同期）
wise-magpie start
```

## コマンド一覧

### 設定

| コマンド | 説明 |
|---------|------|
| `config init [--force]` | デフォルト設定ファイルを生成 |
| `config show` | 現在の設定を表示 |
| `config edit` | エディタで設定を編集 |

### クォータ

| コマンド | 説明 |
|---------|------|
| `quota show` | 残りクォータの推定値を表示（表示時に API 同期） |
| `quota sync` | Anthropic API からクォータを即時同期して表示 |
| `quota correct --session N [--week-all N] [--week-sonnet N]` | `/usage` の値で手動補正（各値は % で指定） |
| `quota history [--days N]` | 使用履歴を表示（デフォルト 7 日） |

### スケジュール

| コマンド | 説明 |
|---------|------|
| `schedule show` | 学習済みのアクティビティパターンを表示 |
| `schedule predict [--hours N]` | アイドルウィンドウの予測（デフォルト 24 時間先まで） |

### タスク

| コマンド | 説明 |
|---------|------|
| `tasks list [--status STATUS]` | タスク一覧（pending/running/completed/failed/all） |
| `tasks add <title> [-d DESC] [-p PRI] [-m MODEL]` | 手動タスク追加 |
| `tasks scan [--path PATH]` | リポジトリスキャン（TODO コメント + キューファイル + 自動タスク） |
| `tasks remove <id>` | タスク削除（実行中は不可） |

### レビュー

| コマンド | 説明 |
|---------|------|
| `review list` | 完了済み・レビュー待ちタスクの一覧 |
| `review show <id>` | タスクの詳細とブランチ差分を表示 |
| `review approve <id>` | ブランチをマージして承認 |
| `review reject <id>` | ブランチを削除して却下 |

### デーモン

| コマンド | 説明 |
|---------|------|
| `start [--foreground]` | デーモン起動 |
| `stop` | デーモン停止 |
| `status` | デーモン・クォータ・タスクの状態表示 |

## タスクソース

wise-magpie は 4 種類のソースからタスクを収集する。

### 1. 手動追加 (`manual`)

```bash
wise-magpie tasks add "Refactor auth module" -d "Split into smaller functions" -p 80
```

### 2. TODO コメントスキャン (`git_todo`)

Git 管理下のファイルから `TODO`, `FIXME`, `HACK`, `XXX` コメントを自動検出。

```python
# TODO: implement rate limiting
# FIXME: this crashes on empty input
```

### 3. キューファイル (`queue_file`)

プロジェクトルートに `.wise-magpie-tasks` または `wise-magpie-tasks.md` を置く。

```markdown
- [ ] Add input validation to API endpoints
- [ ] Write unit tests for payment module
- [x] Already done (チェック済みは無視)
```

### 4. 自動タスク (`auto_task`)

定型的なメンテナンス作業を条件付きで自動生成する。デフォルトでは無効。

#### 有効化

設定ファイルの `[auto_tasks]` セクションを編集:

```toml
[auto_tasks]
enabled = true
work_dir = "."  # 対象リポジトリのパス
```

#### ビルトインテンプレート

| テンプレート | トリガー条件 | デフォルト間隔 |
|-------------|-------------|---------------|
| `run_tests` | 新 commit あり | 24 時間 |
| `update_docs` | コード変更あり | 48 時間 |
| `lint_check` | コード変更あり | 12 時間 |
| `clean_commits` | ブランチに 10+ commit | — |
| `dependency_check` | 時間経過のみ | 168 時間（1 週間） |
| `security_audit` | コード変更あり | 168 時間（1 週間） |
| `test_coverage` | コード変更あり | 48 時間 |
| `dead_code_detection` | コード変更あり | 168 時間（1 週間） |
| `changelog_generation` | ブランチに 5+ commit | — |
| `deprecation_cleanup` | コード変更あり | 336 時間（2 週間） |
| `type_coverage` | コード変更あり | 168 時間（1 週間） |
| `pentest_checklist` | コード変更あり | 720 時間（30 日） |

各テンプレートの詳細は [自動タスク詳細ガイド](docs/auto-tasks.md) を参照。

#### テンプレート個別設定

```toml
[auto_tasks.run_tests]
enabled = true
interval_hours = 12     # 24h → 12h に変更

[auto_tasks.clean_commits]
enabled = false          # 無効化

[auto_tasks.dependency_check]
enabled = true
interval_hours = 336     # 2 週間に変更
```

#### 重複防止

同日に何度 `tasks scan` を実行しても、同じテンプレートのタスクは 1 日 1 回しか生成されない（`source_ref` に日付を含めて重複排除）。

## 優先度スコアリング

タスクの優先度は 0〜100 で自動計算される。

**ソースウェイト:**

| ソース | ベーススコア |
|--------|------------|
| manual | 40 |
| queue_file | 35 |
| issue | 30 |
| auto_task | 25 |
| git_todo | 20 |
| markdown | 15 |

**キーワードブースト（加算）:**

- security / vulnerability: +30
- bug / fix / crash / error: +25
- FIXME: +20
- performance: +15
- HACK / XXX: +15
- refactor / cleanup: +10
- test: +8
- docs: +5

短い説明のタスク（200 文字未満）は、自律実行に適した単純タスクとして最大 +15 のボーナスを得る。

## 設定

設定ファイルは `~/.config/wise-magpie/config.toml` に保存される（`WISE_MAGPIE_CONFIG_DIR` 環境変数で変更可能）。

```toml
[quota]
window_hours = 5            # クォータウィンドウ（時間）
safety_margin = 0.15        # インタラクティブ用に 15% を確保

[quota.limits]
opus = 50                   # Opus のウィンドウあたりメッセージ数
sonnet = 225                # Sonnet のウィンドウあたりメッセージ数
haiku = 1000                # Haiku のウィンドウあたりメッセージ数

[budget]
max_task_usd = 2.0          # タスクあたりの上限（USD）
max_daily_usd = 10.0        # 日あたりの自律実行上限（USD）

[activity]
idle_threshold_minutes = 30 # アイドル判定の閾値
return_buffer_minutes = 15  # 復帰予測の N 分前にタスク開始を停止

[daemon]
poll_interval = 60                  # ポーリング間隔（秒）
auto_sync_interval_minutes = 30     # クォータ自動同期の間隔（分、0 で無効）

[claude]
model = "sonnet"            # デフォルトモデル（opus/sonnet/haiku）
auto_select_model = true    # タスク難度に基づくモデル自動選択
extra_flags = []
```

全設定項目の詳細は [設定リファレンス](docs/configuration.md) を参照。

## 安全設計

- **ブランチ隔離** — タスクは `wise-magpie/task-name-id` ブランチで実行。メインブランチに直接変更を加えない
- **人間によるレビュー** — 完了したタスクは `review approve` で明示的にマージするまで反映されない
- **予算上限** — タスク単位・日単位の USD 上限で意図しないコスト発生を防止
- **クォータ安全マージン** — 推定クォータの 15% をインタラクティブ利用のために確保
- **復帰バッファ** — ユーザーの復帰が予測される 15 分前に新規タスク開始を停止

## 詳細ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [はじめに](docs/getting-started.md) | インストール、初期設定、最初のタスク実行フロー |
| [設定リファレンス](docs/configuration.md) | 全設定項目の詳細、モデル別クォータ/コスト表、設定例 |
| [自動タスク詳細ガイド](docs/auto-tasks.md) | 全 11 テンプレートの仕様、条件チェックロジック、カスタマイズ例 |
| [アーキテクチャ概要](docs/architecture.md) | コンポーネント図、デーモンループ、タスクライフサイクル、安全設計 |
| [トラブルシューティング](docs/troubleshooting.md) | よくあるエラーと解決方法、ログの確認、FAQ |

## 開発

```bash
# 開発用インストール
pip install -e ".[dev]"

# テスト実行
pytest

# テスト（カバレッジ付き）
pytest --cov=wise_magpie
```

## ライセンス

MIT
