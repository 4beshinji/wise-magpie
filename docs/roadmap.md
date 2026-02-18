# ロードマップ

大規模・多人数開発の知見と業界動向（2025-2026）を踏まえた機能拡張計画。

調査ソース: Anthropic 2026 Agentic Coding Trends Report / JetBrains CI/CD Survey 2025 /
Continue.dev Agents / Builder.io Background Agent 比較レポート ほか。

---

## 背景と差別化

商業ツールとの比較:

| ツール | 実行場所 | 月額 | ローカル | クォータ認識 | アイドル起動 |
|--------|---------|------|---------|-------------|-------------|
| Continue.dev Agents | Cloud | $20+ | No | No | No |
| GitHub Copilot Coding Agent | Cloud | $39+/seat | No | No | No |
| Devin | Cloud | $500+ | No | No | No |
| **wise-magpie** | **Local** | **API のみ** | **Yes** | **Yes** | **Yes** |

wise-magpie 固有の強みである「ローカル・アイドル起動・クォータ認識・モデル自動選択」を
最大限に活かす方向で拡張する。

---

## 優先度: 高 — 信頼インフラ

自律エージェント採用の最大障壁は「信頼」であることが業界調査で一貫して示されている
（73% のチームが CI/CD に AI を未導入: JetBrains 2025）。
この層の強化がユーザー採用の壁を最も効果的に下げる。

### ROAD-01: タスク中断・人間エスカレーション機構

**概要**
実行中のタスクが「複数の選択肢があり、どれを適用すべきか判断できない」状況を検出した場合、
タスクを一時停止してユーザーに確認を求める。全タスクが「完走 or 失敗」の二択である現状を改善する。

**ユーザー体験**
```
$ wise-magpie review list
  ID  Status   Title
   7  waiting  Audit code for security issues
       → "SQL インジェクション修正方法が3案あります。どれを適用しますか？"
         [1] パラメータ化クエリに書き換え
         [2] ORM に移行
         [3] 入力バリデーションを追加

$ wise-magpie review respond 7 1
→ タスク再開
```

**実装ポイント**
- `TaskStatus` に `WAITING` を追加
- `executor.py` のプロンプトテンプレートに「判断不能な場合は `{"need_input": true, "question": "...", "options": [...]}` を返せ」という指示を追加
- `review respond <id> <answer>` コマンドを追加
- 再開時に前回の出力とユーザー回答をコンテキストとして付与

**参考**: Anthropic 2026 レポート「エージェントが不確実性を検出し、キー判断点でリクエストする」が最前線トレンドと記載。

---

### ROAD-02: クロスラン学習（実行結果ナレッジベース）

**概要**
タスク完了時に構造化された知見サマリを保存し、同種タスクの次回実行時にコンテキストとして渡す。
同じ問題を毎回ゼロから発見することを防ぎ、継続的に前進するデット削減が可能になる。

**保存内容の例**
```json
{
  "task_type": "security_audit",
  "date": "2026-02-18",
  "findings": ["SQLi in auth.py:42 → 修正済み", "hardcoded secret in config.py:7 → 修正済み"],
  "skipped": [],
  "suggested_next": "依存ライブラリの CVE チェックを優先"
}
```

**次回実行時のプロンプト冒頭**
```
前回の security_audit (2026-02-18) 結果:
  修正済み: SQLi (auth.py:42), hardcoded secret (config.py:7)
  今回は未確認の依存ライブラリ CVE を重点確認してください。
```

**実装ポイント**
- `task_findings` テーブルを DB に追加 (`task_type`, `date`, `findings_json`)
- `executor.py` の出力パース時に findings を抽出・保存
- `auto_tasks.scan()` でプロンプトビルド前に前回知見を注入

**参考**: Block の大規模モノレポ事例「組織的・継続的クリーンアップが成功の鍵」。

---

## 優先度: 高 — 未実装の既存設計を埋める

コードベースに enum 値が既に存在しているが実装がない領域。

### ROAD-03: GitHub Issues 連携

**概要**
`TaskSource.ISSUE`（`models.py` に定義済み、未実装）を実装する。
`gh` CLI が存在する環境ではゼロ追加依存で実現可能。

**コマンド**
```bash
wise-magpie tasks sync-issues --repo owner/repo --label "ai-task" --limit 5
wise-magpie tasks sync-issues --repo owner/repo --milestone "v2.0"
```

**優先度スコアへの反映**
- `bug` ラベル → +20
- `priority: high` ラベル → +25
- GitHub Reactions 数 → 最大 +10

**実装ポイント**
- `tasks/sources/github_issues.py` を新設
- `gh issue list --json` を subprocess で呼び出し
- Issue URL を `source_ref` に保存（dedup キーとして機能）
- 完了時に Issue をクローズするオプション

---

### ROAD-04: Markdown タスクリスト双方向同期

**概要**
`TaskSource.MARKDOWN`（`models.py` に定義済み、未実装）を実装する。
`TODO.md`、`BACKLOG.md`、Obsidian ノート等の `- [ ] ...` 形式を読み込み、
タスク完了時に元ファイルの `[ ]` を `[x]` に書き戻す。

**対応フォーマット**
```markdown
- [ ] Fix authentication bug          ← 取り込み対象
- [x] Update README                   ← スキップ（完了済み）
- [ ] Refactor database layer #high   ← ハッシュタグを優先度ヒントとして使用
```

**実装ポイント**
- `tasks/sources/markdown_todos.py` を新設
- `source_ref = "path/to/file.md:line"` で dedup
- タスク完了後に元ファイルを書き換えるフック

---

## 優先度: 中 — テンプレート拡張

### ROAD-05: アーキテクチャ健全性テンプレート群

業界調査で「長期的技術債務の主因」として挙げられているが現在のテンプレートに存在しない領域。

| テンプレート名 | 内容 | インターバル | トリガー条件 |
|---|---|---|---|
| `architecture_drift` | 循環インポート・モジュール層違反の検出 | 168h | コード変更あり |
| `module_size_check` | 肥大化ファイルの検出と分割提案 | 336h | コード変更あり |
| `api_surface_audit` | public API の後方互換性チェック | 168h | コード変更あり |
| `import_hygiene` | 未使用インポート・スタイル統一 | 24h | コード変更あり |

Python なら `importlib`・`ast` 解析、`pyflakes`、`pydeps` 等を Claude に指示することで実現可能。

---

### ROAD-06: パフォーマンスプロファイリングテンプレート

**概要**
アイドル時間に CPU/メモリプロファイリングを走らせ、前回計測値との差分を報告する。
「何も壊さずにベースラインを計測する」という点でアイドル実行と相性が抜群に良い。

```python
AutoTaskTemplate(
    task_type="perf_regression_check",
    title="Run performance profiling and compare baselines",
    description=(
        "Run cProfile / memory_profiler on the main entry points. "
        "Compare results against the stored baseline in .wise-magpie/perf-baseline.json. "
        "Report any functions with >20% regression and suggest optimizations."
    ),
    interval_hours=168,
    needs_new_commits=True,
)
```

---

### ROAD-07: CI/CD パイプライン健全性テンプレート

JetBrains 2025 調査でCI/CDの最大ペインポイントは「flaky テスト」と「pipeline 設定の複雑化」。

```python
AutoTaskTemplate(
    task_type="pipeline_health",
    title="Check CI pipeline health",
    description=(
        "Analyze recent CI run history (gh run list). "
        "Identify flaky tests by looking at tests that pass/fail inconsistently. "
        "Check workflow YAML files for deprecated actions or redundant steps. "
        "Report findings and suggest fixes."
    ),
    interval_hours=168,
)
```

---

## 優先度: 中 — 実行エンジン強化

### ROAD-08: タスク分解（サブタスクグラフ）

**概要**
`security_audit` や `pentest_checklist` のような複雑なタスクを依存関係付きサブタスクに分解し、
モデルごとの得意領域を活かして並列・逐次実行する。
1セッションで全てをやろうとするコンテキストウィンドウ圧迫を解消する。

**実行例**
```
security_audit (親タスク)
  ├─ [Haiku]  scan_dependencies     → 軽量スキャン、発見物を JSON 出力
  ├─ [Sonnet] analyze_findings      → scan 結果を受け取り優先度付け
  ├─ [Sonnet] apply_fixes           → analyze 結果を受け取り修正実施
  └─ [Haiku]  verify_with_tests     → テスト実行で修正を検証
```

**実装ポイント**
- `Task` モデルに `parent_task_id: int | None` を追加
- `manager.py` にサブタスク展開ロジックを追加
- `scheduler.py` で親タスク完了時に次サブタスクを起動
- サブタスク全完了で親タスクを `COMPLETED` に遷移

---

### ROAD-09: タスクリトライ・バックオフ

**概要**
失敗タスクが `FAILED` のまま放置される現状を改善。
一時的な失敗（ネットワーク、Git コンフリクト）と恒久的失敗（プロンプト不正）を区別する。

**設定**
```toml
[daemon]
max_retries = 3
retry_backoff_minutes = [5, 30, 120]  # 指数バックオフ
```

**実装ポイント**
- `Task` モデルに `retry_count: int = 0`、`next_retry_at: datetime | None` を追加
- `TaskStatus.FAILED` の代わりに `TaskStatus.RETRYING` を経由
- 終端失敗のみ `FAILED` に遷移

---

### ROAD-10: 失敗タスクのコンテキスト保存

**概要**
タスク失敗時に Claude の出力・エラー・スタックトレースを `Task.result_summary` に保存し
（現在のフィールドは未活用）、再実行プロンプトに「前回の失敗原因: ...」を付与する。

**実装ポイント**
- `executor.py` の例外ハンドラで `result_summary` を書き込む
- `auto_tasks.scan()` / `manager.py` でリトライ時に前回 summary を読み込みプロンプトに追記

---

## 優先度: 低 — 観測性・レポーティング

### ROAD-11: 週次サマリーレポート

```bash
wise-magpie report weekly [--output report.md]
```

7日間の自律実行結果を Markdown でまとめる。コスト内訳・完了タスク・発見した問題のサマリ・
クォータ利用率のトレンド。チームでの利用時にマネージャー向け報告書として活用可能。

---

### ROAD-12: コスト効率分析

```bash
wise-magpie quota analyze
```

モデル別・タスク種別のコスト傾向を表示。
「`security_audit` に平均 $0.45 / 実行、今月は 4 回実行で $1.80」といった可視化。
モデル選択のチューニング根拠として使える。

---

## 実装優先順位サマリ

```
Phase 1 (信頼インフラ)
  ROAD-01  タスク中断・エスカレーション     ← ユーザー採用の壁を下げる
  ROAD-02  クロスラン学習                  ← wise-magpie 固有の長期価値

Phase 2 (設計済み機能の実装)
  ROAD-03  GitHub Issues 連携             ← ゼロ追加依存
  ROAD-04  Markdown 双方向同期            ← 既存ワークフローとの統合

Phase 3 (テンプレート拡張)
  ROAD-05  アーキテクチャ健全性            ← 未カバーの技術債務領域
  ROAD-06  パフォーマンスプロファイリング   ← アイドル実行と最高相性
  ROAD-07  CI/CD パイプライン健全性

Phase 4 (エンジン強化)
  ROAD-08  タスク分解（サブタスクグラフ）  ← 最もアーキテクチャ影響大
  ROAD-09  リトライ・バックオフ
  ROAD-10  失敗コンテキスト保存

Phase 5 (観測性)
  ROAD-11  週次サマリーレポート
  ROAD-12  コスト効率分析
```
