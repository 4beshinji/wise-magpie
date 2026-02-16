# はじめに

wise-magpie を使って Claude Max プランのアイドル時間を活用するためのガイドです。

## 前提条件

| 要件 | バージョン | 確認コマンド |
|------|-----------|-------------|
| Python | 3.10 以上 | `python3 --version` |
| Git | 任意 | `git --version` |
| Claude Code CLI | 最新 | `claude --version` |

Claude Code CLI のインストールがまだの場合は、[公式ドキュメント](https://docs.anthropic.com/en/docs/claude-code)を参照してください。

## インストール

### pip を使う場合

```bash
pip install -e ".[dev]"
```

### uv を使う場合

```bash
uv pip install -e ".[dev]"
```

インストール後、`wise-magpie --version` でバージョンが表示されれば成功です。

## 初期設定ウォークスルー

### 1. 設定ファイルの生成

```bash
wise-magpie config init
```

`~/.config/wise-magpie/config.toml` にデフォルト設定ファイルが作成されます。

### 2. 設定ファイルの編集

```bash
wise-magpie config edit
```

エディタが開きます。まず以下の項目を確認・調整してください:

- **クォータ制限** — Claude UI に表示される各モデルの残りメッセージ数に合わせる
- **予算上限** — タスクあたり・日あたりの USD 上限を調整
- **自動タスク** — `[auto_tasks]` の `enabled` を `true` にすると定型タスクが自動生成される

設定の詳細は [設定リファレンス](./configuration.md) を参照してください。

### 3. クォータの確認

```bash
wise-magpie quota show
```

モデルごとの推定残りクォータが表示されます。初回は推定値のため、Claude UI の実際の値で補正することを推奨します:

```bash
wise-magpie quota correct 200 -m sonnet
```

## 最初のタスク実行フロー

### ステップ 1: タスクを追加

```bash
wise-magpie tasks add "Fix authentication bug" -d "Login fails on Safari" -p 80
```

- `-d` : タスクの説明（省略可）
- `-p` : 優先度スコア 0〜100（省略時は自動計算）
- `-m` : 使用モデル（`opus`/`sonnet`/`haiku`/`auto`、省略時は自動選択）

### ステップ 2: リポジトリをスキャン

```bash
wise-magpie tasks scan --path /path/to/your/repo
```

以下の3つのソースからタスクを自動検出します:

- Git 管理下のファイルから `TODO`/`FIXME`/`HACK`/`XXX` コメント
- キューファイル（`.wise-magpie-tasks` または `wise-magpie-tasks.md`）
- 自動タスクテンプレート（有効時）

### ステップ 3: デーモンを起動

```bash
wise-magpie start
```

バックグラウンドでデーモンが起動し、アイドル時にキューからタスクを取り出して実行します。フォアグラウンドで動作を確認したい場合:

```bash
wise-magpie start --foreground
```

### ステップ 4: ステータスを確認

```bash
wise-magpie status
```

デーモンの状態、クォータ残量、実行中/待機中のタスク数、ユーザーのアクティビティ状態が表示されます。

### ステップ 5: 完了タスクをレビュー

```bash
# レビュー待ちの一覧を確認
wise-magpie review list

# 特定タスクの詳細と差分を表示
wise-magpie review show 1
```

### ステップ 6: マージまたは却下

```bash
# 承認してメインブランチにマージ
wise-magpie review approve 1

# 却下してブランチを削除
wise-magpie review reject 1
```

## キューファイルの使い方

プロジェクトルートに `.wise-magpie-tasks` または `wise-magpie-tasks.md` を作成すると、`tasks scan` 時に自動的にタスクとして取り込まれます。

### 書式

```markdown
- [ ] Add input validation to API endpoints
- [ ] Write unit tests for payment module
- [x] Already done task（チェック済みは無視されます）
```

- `- [ ]` で始まる行がタスクとして認識されます
- `- [x]` のようにチェック済みの行は無視されます
- 各行が1つのタスクになります

## よくある最初のつまずき

### Claude CLI が見つからない

```
Error: claude CLI not found. Is Claude Code installed?
```

**原因**: `claude` コマンドにパスが通っていない。

**対処**:
1. `claude --version` で CLI がインストールされているか確認
2. インストールされていなければ [Claude Code の公式ドキュメント](https://docs.anthropic.com/en/docs/claude-code) に従ってインストール
3. パスが通っていない場合は、シェルの設定ファイル（`~/.bashrc` や `~/.zshrc`）に追加

### Git リポジトリではない

```
RuntimeError: Not a git repository: /path/to/dir
```

**原因**: タスク実行ディレクトリが Git リポジトリとして初期化されていない。

**対処**: `git init` でリポジトリを初期化するか、`--path` で正しいリポジトリを指定してください。

### 未コミット変更がある

```
RuntimeError: Repository has uncommitted changes: /path/to/repo.
Commit or stash before running autonomous tasks.
```

**原因**: 安全設計として、未コミットの変更がある状態ではタスクを実行しません。

**対処**: `git commit` で変更をコミットするか、`git stash` で一時退避してください。

### デーモンがすでに実行中

```
Daemon already running (PID 12345)
```

**原因**: 既にデーモンが起動している。

**対処**: `wise-magpie status` で状態を確認するか、`wise-magpie stop` で停止してから再起動してください。

### 設定ファイルが見つからない

```
No config file found at ~/.config/wise-magpie/config.toml
Run 'wise-magpie config init' to create one.
```

**対処**: `wise-magpie config init` で設定ファイルを生成してください。

---

次のステップ: [設定リファレンス](./configuration.md) で詳細な設定オプションを確認
