# Proposal: fix-verdict-read-failclosed

## Why

2026-09-08 09:13 UTC `add-verify-contract-autodraft` 事故：judge 正确判了 **bug-found**（1 个 critical 产品 Bug：`core/verify_contract.py` static serve finally 引用未初始化 `srv`，4 个 CLI 场景崩溃），但裁决结果文件 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 的 summary 字符串含**未转义裸换行**（line 25 col 402）→ 整个文件非法 JSON。随后 14 秒内该 spec 被**推成 pushed**（fenixd.log:47605-47628）：

```
09:13:32 WARN Failed to read verifier result: Invalid control character at: line 25 column 402
09:13:32 INFO Transition: testing → verified
09:13:32 INFO Verification passed → done
09:13:32 INFO Auto-approving (approve_mode=auto)
09:13:45 INFO Transition: done → pushed
```

三层缺口叠加（均已取证定位到行）：

1. **写端分叉**：judge 以相对路径写结果文件，落在 worktree 真实 `.fenix/` 下（add-worktree-verify-progress-copyback 场景），而非 prompt 注入的主树绝对路径。
2. **硬门陈旧放行**：runner 产物硬门（add-judge-artifact-gate D1，`runner.py:1903`）在 `_run_claude` 返回后**立即**校验主树路径，而 worktree→主树拷回发生在**之后**（`runner.py:2115-2133`）——门验到的是**上一轮残留的旧合法文件**（存在/非空/JSON 合法全过，不查 mtime/归属）。与 add-spec-status-modal-budget 事故同根（记忆：judge 产物硬门被 plan-ready 陈旧文件放行），本次为第二次实锤。
3. **读侧 fail-open**：`_read_verifier_result`（`verification.py:2715`）JSONDecodeError → 返回 None，docstring 明写「格式无效视为 verified」；三阶段流水线 `if verifier_status == "bug-found"` 不成立走 else 分支 → verified → done → auto-push。**裁决读不出来 = 按通过放行**。

fail-open 放行已复发 6+ 次（日志 08-27 起：invalid control character ×2、Expecting ',' ×1、unknown status 'success' ×3 / 'blocked-env' ×1 / 'scenario-repaired' ×1，其中 blocked-env 被当 verified 最危险）。阶段 1 读 plan 结果是 fail-closed（≠plan-ready 即降级 legacy，`verification.py:1152`），唯独最关键的最终裁决处相反。

## What Changes

1. **硬门时序与新鲜度（runner 侧）**：worktree verify-progress 拷回前置到门检**之前**（单一事实源：门验的就是本轮实际产出）；门检追加新鲜度约束（结果文件 mtime ≥ 本轮 attempt 启动时刻）；门检追加 status 白名单校验（∈ {verified, bug-found, plan-ready, scenario-repaired}，与读侧共用常量）。任一不满足 → 既有瞬态退避重试通道，不改重试机制。
2. **读侧 fail-closed（pm_engine 三阶段）**：裁决采纳处结果文件**缺失 / 非法 JSON / status 白名单外**一律不得晋级 verified——重派 judge 一次后复读（复用 `_verify_verdict_evidence` 的 retry 模板）；二次仍不可读 → spec blocked + critical 告警 `verdict_result_unreadable`（附解析错误原文与文件路径）。
3. **读侧 fail-closed（legacy 路径）**：旧版 verifier 结果不可读 → blocked + 同款告警，不重试（legacy 本就是降级通道，二次不可读属结构性异常），绝不晋级 verified。
4. **语义反转清账**：`_read_verifier_result` docstring「视为 verified」、`_all_green_fast_path` 注释「写回失败不阻断（本就按 verified 兜底）」等 fail-open 语义引用点同步更新；全库 grep 防漏。
5. **judge prompt 契约加固**：planner-judge.md 结果文件写入要求补一句「必须以合法 JSON 写入（字符串内换行/引号/控制字符须转义），建议用代码生成而非手工拼接」；prompt_builder 动态契约段同步。

## Capabilities

### New Capabilities

- `verdict-result-integrity`：裁决结果文件（`.fenix-run-result.json`）的产生、门检与消费全链完整性——不可读的裁决永远不得等价于「验证通过」。

### Modified Capabilities

（无既有活跃能力被修改——verdict-evidence-taxonomy 管 report.json 分类/证据，judge-artifact-gate 管产物存在性；本 SPEC 新增结果文件完整性维度，与二者正交。）

## Impact

- `core/agent_runner/runner.py`（拷回前置重排 + 门检新鲜度/status 白名单；`_check_agent_result_artifact` 签名扩展）
- `core/pm_engine/verification.py`（三阶段裁决采纳处 retry-then-block；legacy 路径 blocked；docstring 清账）
- `agents/planner-judge.md` + `core/agent_runner/prompt_builder.py`（契约段一行级加固）
- `tests/test_agent_runner_gate.py`（新增：拷回时序/新鲜度/白名单用例）
- `tests/test_verdict_read_failclosed.py`（新建：读侧 fail-closed 全矩阵）
- 风险面：全绿快道机械写回失败从「不阻断（按 verified 兜底）」变为「fail-closed 重试/block」——行为变化点，设计 D6 明示；blocked 无自动出口需人工（与 verdict_evidence_invalid 同语义，接受）；重试一次的额外 judge 轮成本（仅不可读场景触发，用户已确认）。
