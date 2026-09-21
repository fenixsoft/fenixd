# Proposal: refactor-agent-runner-module

## Why

`core/agent_runner/runner.py` 实测 **5087 行**，`AgentRunner` 单类 **4455 行 / 164 个方法**（其中 `_execute_agent_inner` 907 行、`_run_claude` 469 行），另含 4 个结果类与若干模块级函数，混合 7 类职责：claude 子进程引擎、产物门、结果数据结构、维护型 run（管理员/自省/自进化）、provider 熔断转发、V2 测试服务器转发、活性监督转发与延迟统计。巨型单类导致改动牵一发动全身、多 Agent 并发时冲突集中；且 `_run_claude` 的 docstring 因 import 语句插在签名与 docstring 之间而失效（`ast.get_docstring()` 返回 None）。

## What Changes

- **纯内部重构，零行为变化**：把 `runner.py` 中三类**可独立**职责提取到新模块，`AgentRunner` 对提取出的方法保留一行委托。
  - `result_gate.py`：四个结果类 + 门面异常类 + 产物门族（约 587 行）。
  - `maintenance_runs.py`：管理员/自省/自进化 run 及其配套（约 507 行）。
  - `latency.py`：模块级延迟统计纯函数 + `LATENCY_STALL_SECONDS`（约 120 行）。
- **不迁移 `_run_claude` 与其同域辅助**：它与 `runner.py` 模块全局 `subprocess` 名强耦合，而三个既有测试文件以 `monkeypatch.setattr(rmod, "subprocess", ns)` **整体重绑该模块名**后直调 `_run_claude`；迁出会使补丁失效并真 spawn 进程。`core/agent_runner/__init__.py` 的契约明文承诺该补丁缝隙保持可用。故 `claude_cli.py` 不在本变更交付集内。
- **删除仅为测试缝存在的 8 组转发属性 setter/deleter**（`provider_circuits` / `_daily_provider_attempts` / `_daily_provider_warned` / `_daily_reset_date` / `_v2_servers` / `_v2_used_ports` / `_v2_run_seq` / `_extension_baselines`），保留惰性 getter；**11 个直接给这些属性赋值的测试文件 MUST 改为替换组合对象**，并已在 Deliverables 中显式登记为 `kind: modify`。
- **修复 `_run_claude` 的 docstring 位置**（把函数体内那个 `from core.config import ConfigLoader` 移出签名与 docstring 之间）。
- **不拆分 `_execute_agent_inner`（907 行）**——内部拆分风险高，另立 spec（Non-Goal）。
- 拆分**先补 characterization tests**；**不顺手修 bug**（只记疑点清单）。

## Capabilities

### New Capabilities

- `agent-runner-modules`: agent 执行器的模块组织契约——可提取职责边界、门面委托、模块级名字（含补丁缝隙）保持、转发属性收敛与测试改点范围。

### Modified Capabilities

（无——本变更不修改任何既有 spec 级行为要求）

## Impact

- **代码**：`core/agent_runner/runner.py`（5087 行）→ 收敛至 **≤ 3800 行**；新增 `result_gate.py` / `maintenance_runs.py` / `latency.py`。
- **API**：导入路径与调用路径**零改动**。`from core.agent_runner.runner import AgentRunner, AgentRunResult` 等既有 import 保持可用（新模块符号经 `runner.py` re-export）；`core/pm_engine/spec_review.py:21` 与 `core/pm_engine/verification.py:4238` 的直接 import 不受影响。
- **测试**：49 个测试文件引用 `core.agent_runner.runner`，其中绝大多数零修改；**仅 11 个文件因测试缝 setter 收敛必须改**（proposal What Changes 已列，Deliverables 已登记）。新增 characterization tests 独立提交。
- **验收**：全量 `bin/run_full_suite.py` 不引入新失败（须与阶段 0 基线比对）。
- **运行时**：重构期间运行中的 daemon 内存持旧代码，不受影响。
