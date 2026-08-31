# Proposal: refactor-core-packages

## Why

core/ 经多轮开发累计 18 个文件 15,407 行，其中 pm_engine.py（4879 行，PMEngine ~100 方法）与 agent_runner.py（3068 行，AgentRunner ~80 方法）两个巨文件各混杂 8 类职责，占 core 总量 51.5%。单文件巨类导致新功能无明确归属、代码无法整文件理解、改动牵一发动全身，已不利于持续扩展。

## What Changes

- **纯内部重构，零行为变化**：将 `core/pm_engine.py` 拆为 `core/pm_engine/` 包（engine 门面 + dispatch/family/budget/verification/recovery/reporting 六个职责组件），`core/agent_runner.py` 拆为 `core/agent_runner/` 包（runner 门面 + prompt_builder/provider_circuit/liveness/token_budget/v2_server/session/run_files 组件）。
- 采用**组合提取 + 门面**模式：组件持有自己领域的状态，无状态服务构造注入，跨域调用经门面回引；PMEngine/AgentRunner 保留为门面，公共方法及测试引用的 40+ 私有方法保留一行委托——测试调用路径（`engine._process_queue` 等）完全不变。
- 拆分前先补 characterization tests（阶段 0：对将被搬移且无测试覆盖的方法锁定当前行为）。
- worktree_manager/admin_monitor 仅轻梳理（明显坏味道才动，预期改动极小）。
- 拆分中发现的 bug/死代码只记录清单，不顺手修。
- 完整设计已定稿：`docs/superpowers/specs/2026-08-31-core-refactor-design.md`（commit 05396da）。

## Capabilities

### New Capabilities

- `core-package-structure`: core 两巨文件按职责拆包的组织方式与拆分规则——包结构、状态归属（锁与被保护状态同迁、服务注入、门面回引）、外部 API 兼容保证、分阶段验证策略。

### Modified Capabilities

（无——本变更不修改任何既有 spec 级行为要求）

## Impact

- **代码**：`core/pm_engine.py`、`core/agent_runner.py` 重组为同名包；新增 13 个组件模块；`core/worktree_manager.py`、`core/admin_monitor.py` 可能极小改动。
- **API**：零变化。`fenixd.py` 的 `from core.pm_engine import PMEngine` / `from core.agent_runner import AgentRunner`、`core/dashboard/data.py` 的 `from core.agent_runner import clean_old_runs`、27 个测试文件的 import 与私有方法调用路径全部保持可用（经包 `__init__.py` 导出 + 门面委托）。
- **测试**：现有 27 个测试文件零修改；新增 characterization tests 独立 commit。基线 912 passed + 1 个环境性失败（daemon 占用 V2 端口段，与代码无关）；验收标准为不引入新失败。
- **运行时**：重构期间运行中的 daemon 不受影响（内存中是旧代码）；收尾阶段重启 daemon 需用户确认时机。
