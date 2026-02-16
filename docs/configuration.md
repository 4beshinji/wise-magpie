# 設定リファレンス

wise-magpie の全設定項目の詳細リファレンスです。

## 設定ファイルの場所

| 項目 | パス |
|------|------|
| デフォルトディレクトリ | `~/.config/wise-magpie/` |
| 設定ファイル | `~/.config/wise-magpie/config.toml` |
| データベース | `~/.config/wise-magpie/wise-magpie.db` |
| PID ファイル | `~/.config/wise-magpie/wise-magpie.pid` |
| ログファイル | `~/.config/wise-magpie/wise-magpie.log` |

### 環境変数

| 変数名 | 説明 |
|--------|------|
| `WISE_MAGPIE_CONFIG_DIR` | 設定ディレクトリのパスを上書き。設定ファイル・DB・ログ等すべてこのディレクトリ配下に格納される |

```bash
# 例: プロジェクト固有の設定を使う
export WISE_MAGPIE_CONFIG_DIR="$HOME/my-project/.wise-magpie"
wise-magpie config init
```

## 設定コマンド

```bash
wise-magpie config init          # デフォルト設定ファイルを生成
wise-magpie config init --force  # 既存ファイルを上書き
wise-magpie config show          # 現在の設定を表示
wise-magpie config edit          # エディタで編集
```

## 全セクション詳細

### `[quota]` — クォータ管理

| キー | 型 | デフォルト | 説明 |
|------|----|-----------|------|
| `window_hours` | int | `5` | クォータウィンドウの長さ（時間）。Claude Max プランは 5 時間ウィンドウ |
| `safety_margin` | float | `0.15` | インタラクティブ利用のために確保するクォータの割合（0.0〜1.0） |

#### `[quota.limits]` — モデル別メッセージ上限

各モデルの 5 時間ウィンドウあたりのメッセージ上限を設定します。Claude UI に表示される実際の値に合わせて調整してください。

| キー | 型 | デフォルト | 説明 |
|------|----|-----------|------|
| `opus` | int | `50` | Opus のウィンドウあたりメッセージ数 |
| `sonnet` | int | `225` | Sonnet のウィンドウあたりメッセージ数 |
| `haiku` | int | `1000` | Haiku のウィンドウあたりメッセージ数 |

```toml
[quota]
window_hours = 5
safety_margin = 0.15

[quota.limits]
opus = 50
sonnet = 225
haiku = 1000
```

### `[budget]` — 予算制御

| キー | 型 | デフォルト | 説明 |
|------|----|-----------|------|
| `max_task_usd` | float | `2.0` | 1タスクあたりの最大コスト（USD） |
| `max_daily_usd` | float | `10.0` | 1日あたりの自律実行の最大コスト（USD） |

```toml
[budget]
max_task_usd = 2.0
max_daily_usd = 10.0
```

### `[activity]` — アクティビティ検知

| キー | 型 | デフォルト | 説明 |
|------|----|-----------|------|
| `idle_threshold_minutes` | int | `30` | ユーザーがアイドルと判定されるまでの非アクティブ時間（分） |
| `return_buffer_minutes` | int | `15` | ユーザーの復帰予測 N 分前に新規タスク開始を停止 |

```toml
[activity]
idle_threshold_minutes = 30
return_buffer_minutes = 15
```

### `[daemon]` — デーモン設定

| キー | 型 | デフォルト | 説明 |
|------|----|-----------|------|
| `poll_interval` | int | `60` | デーモンのポーリング間隔（秒） |

```toml
[daemon]
poll_interval = 60
```

### `[claude]` — Claude CLI 設定

| キー | 型 | デフォルト | 説明 |
|------|----|-----------|------|
| `model` | string | `"claude-sonnet-4-5-20250929"` | デフォルトモデル（エイリアスまたはフル ID） |
| `auto_select_model` | bool | `true` | タスク難度に基づくモデル自動選択を有効にする |
| `extra_flags` | list | `[]` | claude CLI に渡す追加フラグ |

```toml
[claude]
model = "sonnet"
auto_select_model = true
extra_flags = []
```

### `[auto_tasks]` — 自動タスク生成

| キー | 型 | デフォルト | 説明 |
|------|----|-----------|------|
| `enabled` | bool | `false` | 自動タスク生成の有効/無効 |
| `work_dir` | string | `"."` | 対象リポジトリのパス |

各テンプレートは `[auto_tasks.<template_name>]` サブセクションで個別に設定できます:

| キー | 型 | 説明 |
|------|----|------|
| `enabled` | bool | テンプレートの有効/無効（デフォルト: `true`） |
| `interval_hours` | int | 実行間隔（時間）。テンプレートごとにデフォルト値あり |
| `min_commits` | int | 必要な最小コミット数（`clean_commits` / `changelog_generation` 用） |

```toml
[auto_tasks]
enabled = true
work_dir = "."

[auto_tasks.run_tests]
enabled = true
interval_hours = 24

[auto_tasks.lint_check]
enabled = true
interval_hours = 12

# 不要なテンプレートは無効化
[auto_tasks.clean_commits]
enabled = false
```

テンプレートの全一覧は [自動タスク詳細ガイド](./auto-tasks.md) を参照してください。

## モデルエイリアス

CLI や設定ファイルではエイリアス（短縮名）が使えます。

| エイリアス | フル モデル ID |
|-----------|---------------|
| `opus` | `claude-opus-4-6` |
| `sonnet` | `claude-sonnet-4-5-20250929` |
| `haiku` | `claude-haiku-4-5-20251001` |

```bash
# エイリアスでタスク追加
wise-magpie tasks add "Fix bug" -m opus

# クォータ補正もエイリアスで
wise-magpie quota correct 45 -m opus
```

## モデル別クォータ/コスト表

### メッセージ上限（5 時間ウィンドウあたり）

| モデル | デフォルト上限 |
|--------|--------------|
| Opus (`claude-opus-4-6`) | 50 メッセージ |
| Sonnet (`claude-sonnet-4-5-20250929`) | 225 メッセージ |
| Haiku (`claude-haiku-4-5-20251001`) | 1000 メッセージ |

### コスト推定（USD / 1M トークン）

| モデル | 入力 | 出力 |
|--------|------|------|
| Opus | $15.00 | $75.00 |
| Sonnet | $3.00 | $15.00 |
| Haiku | $0.80 | $4.00 |

## 設定例

### 保守的な設定（コストを抑える）

```toml
[quota]
window_hours = 5
safety_margin = 0.25  # 25% を確保

[quota.limits]
opus = 50
sonnet = 225
haiku = 1000

[budget]
max_task_usd = 1.0    # タスクあたり $1 まで
max_daily_usd = 5.0   # 日あたり $5 まで

[activity]
idle_threshold_minutes = 60  # 60分待ってからタスク開始
return_buffer_minutes = 30   # 30分前に停止

[daemon]
poll_interval = 120    # 2分間隔

[claude]
model = "haiku"        # デフォルトを Haiku に
auto_select_model = false  # 自動モデル選択を無効化

[auto_tasks]
enabled = false        # 自動タスクを無効化
```

### 積極的な設定（クォータを最大活用）

```toml
[quota]
window_hours = 5
safety_margin = 0.10  # 10% のみ確保

[quota.limits]
opus = 50
sonnet = 225
haiku = 1000

[budget]
max_task_usd = 5.0    # タスクあたり $5 まで
max_daily_usd = 20.0  # 日あたり $20 まで

[activity]
idle_threshold_minutes = 15  # 15分でアイドル判定
return_buffer_minutes = 10   # 10分前に停止

[daemon]
poll_interval = 30     # 30秒間隔

[claude]
model = "sonnet"
auto_select_model = true  # 難度に応じてモデルを自動選択

[auto_tasks]
enabled = true
work_dir = "."

[auto_tasks.run_tests]
enabled = true
interval_hours = 12    # テスト実行を 12 時間間隔に

[auto_tasks.security_audit]
enabled = true
interval_hours = 72    # セキュリティ監査を 3 日間隔に
```

---

次のステップ: [自動タスク詳細ガイド](./auto-tasks.md) で全テンプレートの仕様を確認
