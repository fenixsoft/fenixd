# Proposal: refactor-verification-module

## Why

`core/pm_engine/verification.py` 是 core 中最大文件：6304 行、`VerificationPipeline` 约 97 个方法，其中 `_run_three_stage_verification` 单函数即 1165 行（内部已用 `# ── 阶段1/2/3 ──` 段落注释自拟目录）。它混合了至少 10 类职责：被测应用的服务供给（serving worktree/端口/可达性）、三阶段验证主流程、裁决证据校验与合成指令、judge 熔断冻结、env 阻塞升级、场景冻结与交互契约、legacy 验证回退、infra 归因、失败历史、verdict 读取白名单。单文件巨型导致无法整文件理解、多 Agent 并发冲突集中。

## What Changes

- **纯内部重构，零行为变化**：把 `core/pm_engine/verification.py` 按职责拆为 `core/pm_engine/verification/` 子包，`VerificationPipeline` 保留为门面组装类。
- 采用**组合提取 + 门面委托**（沿用 `refactor-core-packages` 先例）。
- **引入 `PipelineContext` 显式注入**，逐步消解 `VerificationPipeline` 对门面 `self._pm.*` 的 495 处回引（其中私有回引 91 处 / 40 个不同目标）——本变更 MUST 先消灭其中对**私有方法的回引**（`self._pm._send_human_escalation_alert`、`self._pm._get_config`、`self._pm._enqueue`、`self._pm._read_verdict` 等），把 logger / project_root / state_machine / config reader / escalation notifier 收敛为 context 的显式成员。
- 拆分**先补 characterization tests**。
- **不顺手修 bug**：发现的缺陷只记录清单。

## Capabilities

### New Capabilities

- `verification-pipeline-modules`: 验证流水线的模块组织契约——子包结构、职责边界、`PipelineContext` 显式依赖、门面委托与测试引用兼容保证。

### Modified Capabilities

（无——本变更不修改任何既有 spec 级行为要求）

## Impact

- **代码**：`core/pm_engine/verification.py`（6304 行）→ `core/pm_engine/verification/` 子包（多职责子模块 + 门面 `__init__.py`）；`verification.py` 删除。
- **API**：零变化。`from core.pm_engine.verification import ...` 与 `engine.py` 门面委托、24 个测试文件（`grep -rl "pm_engine.verification" tests/`）的引用路径保持可用；其中 15+ 处以字符串路径 patch 模块级名字（见 design D9），另需专项保持 patch 语义。
- **测试**：新增 characterization tests 独立提交；验收标准为全量 pytest 不引入新失败。
- **依赖**：`PipelineContext` 为新增内部抽象，不改变对外 API。
- **运行时**：重构期间运行中的 daemon 内存持旧代码，不受影响。
