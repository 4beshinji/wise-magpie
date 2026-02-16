# トラブルシューティング

wise-magpie で発生しやすい問題とその解決方法をまとめています。

## デーモンが起動しない

### PID ファイルの残留

**症状**: `wise-magpie start` で「Daemon already running」と表示されるが、実際にはプロセスが存在しない。

**原因**: 前回のデーモンが異常終了し、PID ファイルが残っている。

**対処**:

```bash
# 状態を確認
wise-magpie status

# PID ファイルを手動削除
rm ~/.config/wise-magpie/wise-magpie.pid

# 再起動
wise-magpie start
```

> `WISE_MAGPIE_CONFIG_DIR` を設定している場合は、そのディレクトリ内の `wise-magpie.pid` を削除してください。

### 権限エラー

**症状**: 設定ディレクトリやデータベースへの書き込み権限がない。

**対処**:

```bash
# ディレクトリの権限を確認
ls -la ~/.config/wise-magpie/

# 必要に応じて修正
chmod 755 ~/.config/wise-magpie/
chmod 644 ~/.config/wise-magpie/config.toml
chmod 644 ~/.config/wise-magpie/wise-magpie.db
```

## タスクが実行されない

`wise-magpie status` で現在の状態を確認し、6 段階チェックのどこで止まっているかを特定してください。

### チェック 1: ユーザーがアクティブと判定される

**表示例**: `Activity: user active`

**原因**: `pgrep -f claude` でプロセスが検出されている。wise-magpie は Claude を使用中のユーザーの邪魔をしないよう、アクティブ時はタスクを実行しません。

**対処**: Claude の使用を終了するか、バックグラウンドの Claude プロセスがないか確認してください。

### チェック 2: アイドル時間が不足

**ログ例**: `User idle only 10m (threshold: 30m)`

**原因**: `idle_threshold_minutes`（デフォルト 30 分）に達していない。

**対処**: 待つか、設定値を下げてください。

```toml
[activity]
idle_threshold_minutes = 15
```

### チェック 3: 復帰予測による停止

**ログ例**: `User predicted to return in 10m (buffer: 15m)`

**原因**: 学習したパターンからユーザーの復帰が近いと予測されている。

**対処**: `return_buffer_minutes` を短くするか、しばらく待ってください。

### チェック 4: 予算上限に達した

**ログ例**: `Daily autonomous limit reached: $10.00 / $10.00`

**対処**: 翌日まで待つか、予算上限を引き上げてください。

```toml
[budget]
max_daily_usd = 20.0
```

### チェック 5: 待機タスクがない

**ログ例**: `No pending tasks in queue`

**対処**: タスクを追加してください。

```bash
wise-magpie tasks add "Some task"
# または
wise-magpie tasks scan --path /path/to/repo
```

### チェック 6: 別のタスクが実行中

**ログ例**: `Task #3 is already running`

**原因**: wise-magpie は同時に 1 タスクしか実行しません。

**対処**: 実行中のタスクが完了するのを待ってください。

## クォータの手動補正

推定値と実際のクォータが乖離している場合、Claude UI に表示される残りメッセージ数で補正できます。

```bash
# モデルを指定して補正（推奨）
wise-magpie quota correct 180 -m sonnet
wise-magpie quota correct 40 -m opus

# 確認
wise-magpie quota show
```

## 「Repository has uncommitted changes」エラー

```
RuntimeError: Repository has uncommitted changes: /path/to/repo.
Commit or stash before running autonomous tasks.
```

**原因**: 安全設計として、未コミットの変更がある状態ではブランチの作成・切り替えを行いません。

**対処**:

```bash
# 変更をコミット
cd /path/to/repo
git add -A && git commit -m "WIP"

# または一時退避
git stash
```

## 「claude CLI not found」エラー

```
Error: claude CLI not found. Is Claude Code installed?
```

**原因**: `claude` コマンドがシステムの PATH に含まれていない。

**対処**:

```bash
# インストール確認
which claude
claude --version

# パスが通っていなければシェル設定に追加
# 例: ~/.bashrc や ~/.zshrc に追記
export PATH="$PATH:/path/to/claude"
```

## ログファイルの確認

デーモンのログは以下の場所に保存されます:

```
~/.config/wise-magpie/wise-magpie.log
```

```bash
# 最新のログを確認
tail -50 ~/.config/wise-magpie/wise-magpie.log

# リアルタイムで監視
tail -f ~/.config/wise-magpie/wise-magpie.log
```

> `WISE_MAGPIE_CONFIG_DIR` を設定している場合は、そのディレクトリ内の `wise-magpie.log` を確認してください。

### ログレベル

デーモンは `INFO` レベルでログを出力します。主なログメッセージ:

| メッセージ | 意味 |
|-----------|------|
| `Daemon started (PID ...)` | デーモン起動 |
| `Starting task #N: ...` | タスク実行開始 |
| `Task #N completed successfully` | タスク正常完了 |
| `Task #N failed: ...` | タスク失敗（エラー詳細付き） |
| `Not executing: ...` | 実行判定で不合格（理由付き） |
| `Upgrading ... -> ...: ...` | モデルアップグレード |
| `Downgrading ... -> ...: quota exhausted` | クォータ不足によるダウングレード |
| `Daemon shutting down` | デーモン停止 |

## 完了タスクのレビューフロー

```bash
# 1. レビュー待ちタスクの一覧
wise-magpie review list

# 2. タスクの詳細を確認（結果サマリー・コミットログ・差分）
wise-magpie review show <task_id>

# 3a. 承認 → メインブランチにマージ
wise-magpie review approve <task_id>

# 3b. 却下 → 作業ブランチを削除
wise-magpie review reject <task_id>
```

### マージ失敗時

`review approve` でコンフリクトが発生した場合:

```
Merge failed: ...
Resolve conflicts manually and re-run, or reject this task.
```

**対処**:

```bash
# 手動でマージ
cd /path/to/repo
git merge wise-magpie/task-branch-name

# コンフリクトを解消してコミット
git add .
git commit

# または却下
wise-magpie review reject <task_id>
```

## FAQ

### Q: デーモンはどのくらいのリソースを消費しますか？

A: デーモン自体は非常に軽量で、`poll_interval`（デフォルト 60 秒）ごとに `pgrep` と簡単な DB クエリを実行するだけです。タスク実行時のみ Claude CLI プロセスが起動します。

### Q: 複数のリポジトリでタスクを実行できますか？

A: タスク追加時に作業ディレクトリが記録されます。`auto_tasks.work_dir` は 1 つのリポジトリのみ指定できますが、手動追加や複数のキューファイルから異なるリポジトリのタスクを投入できます。

### Q: タスクの同時実行はできますか？

A: いいえ。安全性のため、同時に実行されるタスクは 1 つのみです。1 つのタスクが完了してから次のタスクが開始されます。

### Q: クォータウィンドウはいつリセットされますか？

A: Claude Max プランのクォータウィンドウは 5 時間で回転します。wise-magpie はウィンドウ開始時刻を記録し、経過時間を追跡します。正確な値を維持するために、定期的に `quota correct` で Claude UI の値と同期することを推奨します。

### Q: 自動タスクを特定のモデルで実行できますか？

A: 自動タスクはデフォルトで難度に応じたモデル自動選択が行われます。`[claude] auto_select_model = false` に設定すると、すべてのタスクが `[claude] model` で指定したモデルで実行されます。手動タスクの場合は `tasks add -m opus` のように個別にモデルを指定できます。

### Q: データベースをリセットするには？

A: データベースファイルを削除すると初期状態に戻ります。

```bash
rm ~/.config/wise-magpie/wise-magpie.db
```

次回のコマンド実行時に自動的に再作成されます。タスク履歴・使用量記録・学習パターンはすべて失われます。

### Q: wise-magpie を完全にアンインストールするには？

A: 以下の手順でアンインストールできます。

```bash
# 1. デーモンを停止
wise-magpie stop

# 2. パッケージをアンインストール
pip uninstall wise-magpie

# 3. 設定・データディレクトリを削除
rm -rf ~/.config/wise-magpie/
```

### Q: フォアグラウンドモードとバックグラウンドモードの違いは？

A: `wise-magpie start` はデフォルトでバックグラウンド（デーモン化）で起動し、ターミナルから切り離されます。`wise-magpie start --foreground` はフォアグラウンドで起動し、ログがターミナルにも出力されるためデバッグに便利です。`Ctrl+C` で停止できます。

---

関連ドキュメント:
- [はじめに](./getting-started.md)
- [設定リファレンス](./configuration.md)
- [自動タスク詳細ガイド](./auto-tasks.md)
- [アーキテクチャ概要](./architecture.md)
