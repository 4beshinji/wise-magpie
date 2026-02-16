# 自動タスク詳細ガイド

wise-magpie は定型的なメンテナンス作業を条件付きで自動生成し、キューに投入できます。

## 仕組み概要

1. `wise-magpie tasks scan` を実行すると、有効な自動タスクテンプレートの条件がチェックされる
2. 条件を満たしたテンプレートから `Task` オブジェクトが生成される
3. `source_ref` に `"{task_type}:{YYYY-MM-DD}"` の形式で日付を含め、重複を排除する
4. 新規タスクのみがデータベースに挿入され、優先度が自動計算される

## 有効化

デフォルトでは無効です。設定ファイルで有効化してください:

```toml
[auto_tasks]
enabled = true
work_dir = "."  # スキャン対象のリポジトリパス
```

`work_dir` は `tasks scan --path` で指定したパスより優先されます（設定がある場合）。

## 全 11 テンプレート一覧

| # | task_type | タイトル | 説明 | デフォルト間隔 | 条件 | 難度 |
|---|-----------|---------|------|--------------|------|------|
| 1 | `run_tests` | Run test suite | テストスイートを実行し、失敗を調査・修正 | 24h | 新コミットあり | SIMPLE |
| 2 | `update_docs` | Update documentation | 最近のコード変更に合わせてドキュメントを更新 | 48h | コード変更あり | SIMPLE |
| 3 | `lint_check` | Run linter and fix issues | リンター実行、自動修正、残る警告に対応 | 12h | コード変更あり | SIMPLE |
| 4 | `clean_commits` | Clean up commit history | コミット履歴の整理、fixup の squash | — | ブランチに 10+ コミット | MEDIUM |
| 5 | `dependency_check` | Check dependency updates | 依存パッケージの更新確認とセキュリティ・互換性評価 | 168h（1 週間） | 時間経過のみ | MEDIUM |
| 6 | `security_audit` | Audit code for security issues | OWASP Top 10 を中心としたセキュリティ脆弱性スキャン | 168h（1 週間） | コード変更あり | COMPLEX |
| 7 | `test_coverage` | Generate tests for uncovered code | カバレッジの低い箇所にテストを追加 | 48h | コード変更あり | MEDIUM |
| 8 | `dead_code_detection` | Detect and remove dead code | 未使用のインポート・関数・変数を検出し削除 | 168h（1 週間） | コード変更あり | SIMPLE |
| 9 | `changelog_generation` | Generate changelog from recent commits | コミット履歴から CHANGELOG を生成・更新 | — | ブランチに 5+ コミット | SIMPLE |
| 10 | `deprecation_cleanup` | Clean up deprecated code usage | 非推奨 API の使用箇所を検出し移行 | 336h（2 週間） | コード変更あり | COMPLEX |
| 11 | `type_coverage` | Add type annotations to untyped code | 型アノテーションのないコードに型ヒントを追加 | 168h（1 週間） | コード変更あり | MEDIUM |

**難度** 列はモデル自動選択時の基準です（後述「難度別モデル自動選択」を参照）。

## 条件チェックロジック

各テンプレートは以下の条件パラメータの組み合わせで発火が制御されます:

### `interval_hours`（時間ベース）

前回の同タイプタスクが完了してから指定時間が経過した場合に条件を満たします。過去に一度も完了していない場合は常に条件を満たします。

### `needs_new_commits`

`interval_hours` で指定した期間内にリポジトリに新しいコミットがある場合のみ条件を満たします。`git log --since=...` で判定します。

### `needs_code_changes`

`interval_hours` で指定した期間内に追加・変更・リネームされたファイルがある場合のみ条件を満たします。`git log --diff-filter=ACMR --since=...` で判定します。

### `min_commits`

現在のブランチが main/master から分岐した後のコミット数が指定値以上の場合に条件を満たします。`git rev-list --count main..HEAD` で判定します。

### 条件評価フロー

```
テンプレートごとに:
  1. [auto_tasks.<task_type>] で enabled = false → スキップ
  2. interval_hours > 0 かつ前回完了からの経過時間が不足 → スキップ
  3. min_commits > 0 かつブランチのコミット数が不足 → スキップ
  4. needs_new_commits かつ期間内に新コミットなし → スキップ
  5. needs_code_changes かつ期間内にコード変更なし → スキップ
  6. すべての条件を通過 → タスク生成
```

## テンプレート個別設定

各テンプレートは `[auto_tasks.<task_type>]` セクションで個別に制御できます。

### 基本パターン

```toml
# テンプレートを無効化
[auto_tasks.clean_commits]
enabled = false

# 実行間隔を変更
[auto_tasks.run_tests]
enabled = true
interval_hours = 12     # 24h → 12h に短縮

# コミット閾値を変更
[auto_tasks.changelog_generation]
enabled = true
min_commits = 10        # 5 → 10 に引き上げ
```

### 全テンプレートのデフォルト設定

```toml
[auto_tasks.run_tests]
enabled = true
interval_hours = 24

[auto_tasks.update_docs]
enabled = true
interval_hours = 48

[auto_tasks.lint_check]
enabled = true
interval_hours = 12

[auto_tasks.clean_commits]
enabled = true
min_commits = 10

[auto_tasks.dependency_check]
enabled = true
interval_hours = 168

[auto_tasks.security_audit]
enabled = true
interval_hours = 168

[auto_tasks.test_coverage]
enabled = true
interval_hours = 48

[auto_tasks.dead_code_detection]
enabled = true
interval_hours = 168

[auto_tasks.changelog_generation]
enabled = true
min_commits = 5

[auto_tasks.deprecation_cleanup]
enabled = true
interval_hours = 336

[auto_tasks.type_coverage]
enabled = true
interval_hours = 168
```

## 重複防止の仕組み

自動タスクの `source_ref` は `"{task_type}:{YYYY-MM-DD}"` の形式です（例: `run_tests:2026-02-16`）。

- `tasks scan` 時に `(source, source_ref)` のペアでデータベースと照合
- 同じ日に同じテンプレートのタスクが既に存在する場合は挿入されない
- 1 日に何度 `tasks scan` を実行しても、同じテンプレートのタスクは最大 1 つ

## 難度別モデル自動選択

`[claude] auto_select_model = true`（デフォルト）の場合、タスクの難度に応じてモデルが自動選択されます。

| 難度 | 割り当てモデル | 判定基準 |
|------|--------------|---------|
| SIMPLE | Haiku (`claude-haiku-4-5-20251001`) | docs, lint, format, typo, clean, dead code, changelog 等のキーワード |
| MEDIUM | Sonnet (`claude-sonnet-4-5-20250929`) | 上記に該当しない一般的なタスク |
| COMPLEX | Opus (`claude-opus-4-6`) | security, vulnerability, architecture, migration, performance 等のキーワード |

### モデルアップグレード判定

以下の条件で、より高性能なモデルに自動アップグレードされることがあります:

- **ウィンドウ残り時間が 1.5 時間未満** かつ **クォータ残量が 30% 以上**: クォータが余っているため活用
- **今後 8 時間以内に 6 時間以上のアイドルが予測される** かつ **クォータ残量が 40% 以上**: 長時間アイドルでクォータが失われる前に活用

### クォータ不足時のダウングレード

選択されたモデルのクォータが不足している場合、1 段階下のモデルにダウングレードされます（Opus → Sonnet → Haiku）。2 段階ダウンまで試行します。

## カスタマイズ例

### テスト重視の設定

```toml
[auto_tasks]
enabled = true
work_dir = "."

# テストを頻繁に実行
[auto_tasks.run_tests]
enabled = true
interval_hours = 6

# カバレッジもこまめにチェック
[auto_tasks.test_coverage]
enabled = true
interval_hours = 24

# ドキュメント系は無効化
[auto_tasks.update_docs]
enabled = false

[auto_tasks.changelog_generation]
enabled = false
```

### セキュリティ重視の設定

```toml
[auto_tasks]
enabled = true
work_dir = "."

# セキュリティ監査を頻繁に
[auto_tasks.security_audit]
enabled = true
interval_hours = 48

# 依存関係チェックも頻繁に
[auto_tasks.dependency_check]
enabled = true
interval_hours = 72

# 非推奨 API のクリーンアップも頻繁に
[auto_tasks.deprecation_cleanup]
enabled = true
interval_hours = 168
```

---

次のステップ: [アーキテクチャ概要](./architecture.md) でシステムの内部構造を理解
