# fix-codefix-rollup-archive-read

## Why

evo-add-codefix-digest-cost-metrics 落地的链级 rollup 在本窗口实测恒全零：仅有的两次真实输出（.fenix/logs/fenixd.log:31407 的 runs=2/resolved=34/turns=0 与 :31583 的 runs=1/resolved=19/turns=0）及落盘快照 .fenix/code-review/fix-progress.json 的 chain_rollup 全零、avg_turns_per_item=0.0。根因是结构性的：_read_run_metrics（core/code_fix.py:471-497，路径构造 :479）只读顶层 .fenix/runs/<run_id>.jsonl、缺失按零贡献，而 daemon 每 300 秒 runs retention 清理（fenixd.py:884-891 → core/dashboard/data/runs.py:1045 runs_retention_check）把终态 run 移入 .fenix/runs/archive/——code-fix 链横跨数小时，链终局时除末批外的 run 文件必然早已移档，turns 恒零。该 SPEC 留下的「rollup 数据积累后再评估批结构参数」决策口因此永远没有输入，其 capability 契约「覆盖链中全部 run 不漏样本」实质未兑现。

## What Changes

1. _read_run_metrics 改双路径回退：先顶层 .fenix/runs/<run_id>.jsonl，缺失回退 .fenix/runs/archive/<run_id>.jsonl（对齐 core/admin_monitor.py:3401-3405 _admin_run_file 仓内先例）。
2. 归零语义收窄为「顶层与归档两处皆缺」；fail-open 与「归档缺失不炸链终局」语义保留。
3. capability spec 补契约澄清：run 归档计数含 retention 归档副本。

## Non-Goals

- 不做历史链的追溯重算（一次性归因用只读脚本，不入框架）。
- 不重启预聚类/批结构评估（cost-metrics 非目标维持）。
- 不改 rollup 触发时机、出账清账语义与 retention 周期。

## Impact

- Specs: specs/codefix-digest-cost-metrics/spec.md（MODIFIED：数据可达性——归档副本计入样本覆盖）
- Code: core/code_fix.py（_read_run_metrics 双路径回退）
- Tests: tests/test_codefix_digest_metrics.py（新增移档场景与双缺失边界）
- 行为：链终局 rollup 在 run 已被 retention 移档后仍计得真实 turns/工具数；以本窗口两个真实零值输出为回归样本。