# Proposal: fix-robustness-edge-cases

## Why

代码库存在若干**可复现**的边缘情况缺陷，均为静默失败或误判，且修复方式在仓库内已有先例：

1. **spec 名互为前缀导致 run 流误归属**：`recovery.py` 已补精确归属守卫（用 `run_spec_part` 解析出完整 spec 名再全等比较），但**其余 6 处同型 glob 未补**——`worktree_manager` 的残留判定、`liveness` 的活性判定、`engine._spec_has_recent_run_activity`、`budget` 的预算豁免、`run_task_track`、`verification` 的 planner 耗时。spec `a-b` 会误命中 `impl-a-b-c-*.jsonl`，凭空制造「近期活动」豁免真 stale，或误把在跑的 run 判为残留。已实测复现。
2. **`admin_alerts.json` 读损坏 → 静默清库**：读侧对 `JSONDecodeError` 返回 `[]`，随后的读-改-写原子回写会以空数组为底、把全部历史（上限 150 条）无声抹掉。这是唯一人工告警通道的单点。
3. **旁路 logger 写丢**：`Logger` 只给 `logging.getLogger("fenixd")` 挂 handler，若干模块用裸 `getLogger("pm_engine")` / `getLogger(__name__)` 挂在 root（无 handler）下，其 WARNING/ERROR **不进结构化日志**。已实测 `verify_scenarios` 的告警在 `fenixd.log` 中 0 命中。

## What Changes

- **统一 spec 归属解析**：把逐条 `glob(f"{prefix}-{spec_name}-*.jsonl")` 的判定点全部改为经 `run_spec_part` 解析后全等比较（沿用 `recovery.py` 既有守卫为唯一范式）。
- **前置：补齐 `run_spec_part` 的后缀解析**：该解析器现不识别瞬态重试后缀 `-r<n>`，对仓库内已有的 40 个 `<prefix>-<spec>-<ts>-a<n>-r<m>.jsonl` 文件返回整段而非 spec 名；不先补齐就上全等守卫，会把在跑的 run 判为「非本 spec」（假阴性 → 误报 stuck），净效果为负。仓库内 `admin_monitor._spec_from_run_id` 已有正确处理且记录了该漏剥引发的前次事故。
- **`admin_store` 读侧抗损坏**：损坏时先把原文件改名留底（`.corrupt-<ts>`）再返回空；写回前对记录数做下限保护（旧记录全丢时拒绝写回并告警）。
- **logger 门面统一**：收敛旁路 `getLogger` 用法到可传播的 `fenixd.` 层级或注入 Logger 实例；修复后新增一条针对「非 fenixd 层级 getLogger」的静态检查或测试。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `human-escalation-alerts`: 告警存储读损坏时不得静默清空历史。
- （可能的既有能力）`run-artifact-retention` / `worktree-hygiene` / `admin-health-monitor`: spec-run 归属判定须为全等匹配。

## Impact

- **代码**：`core/pm_engine/budget.py`、`core/pm_engine/engine.py`、`core/pm_engine/verification.py`、`core/agent_runner/liveness.py`、`core/worktree_manager.py`、`core/run_task_track.py`、`core/admin_store.py`、`core/logger.py`、若干旁路 logger 模块（`verify_scenarios.py`、`spec_integrity.py`、`dashboard/server.py`、`scenario_static_check.py`、`dashboard/registry.py`）。
- **行为**：仅为修正误判与静默失败，不改变正常路径结果。
- **测试**：新增前缀命中不误归属的用例、admin 存储损坏用例、日志落盘用例。
- **注意**：本 spec 与可读性重构有文件重叠，依赖链排在重构之后。
