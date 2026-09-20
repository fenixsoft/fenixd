## Why

代码审查发现问题修复 SPEC（由 code-review 台账选中条目机械生成）。

## What Changes

- 修复以下审查发现（SPEC `fix-cr-robustness`）：

  - [minor] float() 直接转换运行超时可能抛 TypeError（core/agent_runner/liveness.py:996）

## Capabilities

### New Capabilities

- 修复 code-review 台账中选中的代码质量问题。

## Impact

- 修改 `## Deliverables` 声明段所列文件。
