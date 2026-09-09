# Design — remove-auto-run-cleanup

## Context

runs 产物当前有两条生命周期路径并存：(1) dashboard `project_summary` 每次请求触发的 `cleanup_runs`——按 `runs.keep`（默认 50）数量裁剪、超出移入 archive，且 `active_ids` 只保护 STATE.md 引用的 run；(2) spec 归档（`fenix_archive.py`）目前只移动 `spec/changes/<name>/` 目录，不触碰 runs。事故证明 (1) 在「多实例 + 旧码 + STATE.md 空文件」组合下等价于无保护破坏：任意持有旧码的实例都能绕过归档机制直接删除。

## Goals / Non-Goals

- Goals：runs 顶层产物只增不减；归档动作唯一入口 = spec 归档；删除全部按数量/时间的自动裁剪代码与配置 UI。
- Non-Goals：不做 STATE.md 空文件修复（独立问题）；不改 `get_runs` 回读逻辑（`include_archive=True` 已覆盖）；不引入 runs 产物的大小/时间上限（明确不做——「只增不减」是本次选定的保留语义）。

## Decisions

### D1 删除而非注释禁用
`cleanup_runs`/`clean_old_runs`/`RUNS_KEEP`/节流常量整体删除。理由：保留死代码会诱导未来恢复自动清理语义；git 历史可回溯。`tests/test_dashboard_index.py` 的 cleanup_runs 用例同步删除。

### D2 run_id→spec 推断迁至 run_files.py（单一实现）
`_run_spec_part` 迁出 data.py → `run_files.py` 公开名 `run_spec_part`。分层依据：现有依赖方向是 dashboard → agent_runner（data.py 已 import clean_old_runs），反向禁止。`bin/fenix_archive.py`（无 core 依赖的独立脚本）通过 `sys.path.insert(0, str(project_root))` 后 `from core.agent_runner.run_files import archive_spec_runs` 复用同一实现；不复制正则逻辑。

### D3 archive_spec_runs 语义
`archive_spec_runs(runs_dir: Path, spec_name: str) -> int`：
- 仅扫描 `runs_dir` 顶层 `*.jsonl`（不含 archive/ 递归）；
- `run_spec_part(p.stem) == spec_name` 的文件 `Path.replace` 到 `runs_dir/archive/<同名>`（archive 目录 `mkdir(parents=True, exist_ok=True)`）；
- 同名冲突（attempt 文件名全局唯一，正常不会发生）以归档侧为准：目标已存在时删除顶层副本（与原 clean_old_runs 的去重分支一致）；
- OSError（单文件权限等）记 warning 继续处理其余文件，返回成功移动数；runs_dir 不存在返回 0。
- 不删除任何文件（除上述同名列顶层副本）、不修改文件内容、不改 mtime 语义。

### D4 fenix_archive.py 挂钩 fail-open
`archive_change()` 中 change 目录移动成功后执行 run 归档；任何 OSError/ImportError 仅向返回 dict 追加 `"runs_archived": <n>` / `"runs_archive_warning": <msg>` 字段并照常返回成功——runs 归档失败不得阻断 change 归档主流程（change 目录已移动，回滚复杂度更高）。

### D5 runs.keep 配置残留无害化
ConfigLoader 无 schema 强校验，删除消费方后残留 YAML 键不影响运行；后端仅删 data.py 的溯源映射（`sources["runs.keep"]` 等）与 MiscSettingsPanel 的 UI 输入。不写配置迁移。

## Risks / Trade-offs

- **遗漏调用方/引用**：实现时全库 `grep -rn "clean_old_runs\|RUNS_KEEP\|cleanup_runs\|runs.keep\|runs\.keep"`（排除 .claude/worktrees、archive/ 历史 spec 文档、node_modules、dist）确认清零；tests 里引用同步改写。
- **dist 漏重建 → UI 验证假阴性**：tasks 显式含 dist 重建+提交步骤，UI 验证打主树 8787。
- **「只增不减」的长期膨胀**：接受。单 run 产物 ~50KB-1MB 量级，增长由 spec 归档动作自然分流；若未来需要容量治理，必须以带审计的新 SPEC 重新设计，不得恢复匿名裁剪。

## Open Questions

无。
