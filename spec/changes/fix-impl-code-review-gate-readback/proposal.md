## Why

姊妹问题 `fix-impl-code-review-writepath` 修的是**写侧**（让报告稳定落进 worktree）。但读侧本身也有一处独立缺陷会被同类现象触发：`_check_impl_code_review_artifact` 只在 **worktree** 内找
`.fenix/verify-progress/<spec>/code-review.json`，**没有任何回退路径**。因此只要报告被写到主树
（既可能是写侧误导，也可能是人工运维、旧版本行为、或 agent 用绝对路径的自救写），门就恒判「报告
缺失」——而这恰恰是框架自己注入的 `--add-dir <主树>/verify-progress` 明确授权过的落点。

2026-09-21 实测：`add-freeze-stop-inflight-agents` 主树 `/root/fenixd/.fenix/verify-progress/<spec>/code-review.json`
**存在且格式完全合规**（`status: completed`、`findings: []`、summary 完整），但门连续 7 次判
「报告缺失」，因为门只看 worktree。**写侧修好不等于读侧安全**——读侧必须对「合规报告已在主树」
这一确定事实 fail-safe 而非 fail-closed 到死。

## What Changes

- **`_check_impl_code_review_artifact` 增主树回退**：worktree 路径缺失时，回退读
  `<project_root>/.fenix/verify-progress/<spec>/code-review.json`；两处读到即按**同一套**校验
  （status 白名单 / findings 与 dispositions 对账 / reason 非空）判定，不再「一处缺失即判失败」。
- **新鲜度守卫**：回退读到的文件 MUST 过 mtime 新鲜度（沿用 `_check_artifact_json_file` 的
  `_ARTIFACT_FRESHNESS_GRACE_SECONDS` 规则，且 `is_resumed_worktree=True` 时跳过硬拦）——防上一轮/
  其它 spec 的陈留主树报告冒充本轮产物。为此把 `run_started_at` / `is_resumed_worktree` 从
  `_check_impl_result_artifact` 透传进本门。
- **缺失归因文案**：仅在**两处均缺失**时才报「报告缺失」，且文案 MUST 同时给出两个已探测路径
  （便于取证），不再只报 worktree 相对路径。

## Capabilities

### New Capabilities

- `impl-code-review-gate-readback`: 收尾审查产物门的读侧容错——worktree 优先、主树回退、统一校验
  与新鲜度守卫、双路径缺失归因。

## Impact

- 受影响代码：`core/agent_runner/result_gate.py`（`_check_impl_code_review_artifact` 及其调用点
  `_check_impl_result_artifact`）。
- 受影响测试：`tests/test_impl_code_review_gate.py`。
- 行为影响面：仅在 `verify.impl_code_review` 开启时生效；开关关闭仍是零校验放行。worktree 已有
  合规报告时行为**完全不变**（worktree 优先）。
- 非目标：不做自动「主树 → worktree」回拷（门是读侧，不产生写副作用）；写侧修正由
  `fix-impl-code-review-writepath` 承担。
