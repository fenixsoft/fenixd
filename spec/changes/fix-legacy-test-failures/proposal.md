# Proposal: fix-legacy-test-failures

## Why

当前主线全量测试基线为 **12 failed / 10181 passed**（2026-11-10 本机实测约 11m40s），并非全绿。已批准的 Windows PAL 架构评估（`docs/superpowers/specs/2026-11-10-windows-native-support-pal-design.md` §7 SPEC-0）与用户定夺（2026-11-10）：存量失败由独立前置 SPEC 清零，后续 SPEC-1（add-platform-abstraction-layer）验收维持「通过所有单元测试」原口径——存量失败不先清零，SPEC-1 的全绿验收无法成立。至少 `test_logger_no_bypass` 为 core/ 真实违例（裸 `getLogger`，断言指认 dsh_session_tidy），非环境差异。

## What Changes

- 逐项修复 12 个存量失败测试（精确清单见 tasks.md，来自 2026-11-10 全量实测）：
  - **真实违例**：修实现（如 test_logger_no_bypass 指认的裸 `getLogger` 违例点）。
  - **过时断言**：断言与现行正确行为脱节时修断言，并注明归因。
  - **测试隔离/环境类**：修测试自身的隔离与确定性（顺序依赖、共享状态、时序敏感）。
- 不引入新功能、不改变任何行为契约、零新增第三方依赖。
- 每个失败的归因（违例/断言/环境 + 证据）记录在 tasks.md 对应任务完成说明中。

## Capabilities

### New Capabilities

- `legacy-test-baseline-green`: 主线全量测试零失败的基线契约——`python3 -m pytest tests/ -q` 以 0 failed 收场，且修复不掩盖真实缺陷（逐项归因可追溯）。

### Modified Capabilities

（无——存量失败均为既有行为的缺陷或测试债，不修改任何既有能力的 spec 级 REQUIREMENT。）

## Impact

- 修改：失败测试对应的 tests/ 文件与少量 core/ 实现（精确清单以 tasks.md 为准）。
- 行为契约：除真实违例修复外不改变既有行为；全量测试 0 failed。
- 后续：本 SPEC 完成后 `add-platform-abstraction-layer`（已挂 `depends_on: fix-legacy-test-failures`）自动解除阻塞进入调度。
