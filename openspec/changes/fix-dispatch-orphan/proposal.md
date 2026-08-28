# Proposal: fix-dispatch-orphan

## Why

2026-08-27 事故实证：子 SPEC `fix-fix-stashpop-deadlock-and-provider-fuse` 的实现已成功合并（14:53），却在 daemon 重启瞬间丢失「implemented→验证」闭环；随后父 SPEC 每 30 分钟周期扫描把该子 SPEC 反复重置回 ready 并清空 implementer_run/tester_run，且因同状态更新不产生任何事件，恢复分支又只认「无 error 且无 implementer_run」的 ready，导致三个 ready spec（add-spec-context-menu、fix-improve-verify-adjudication、fix-fix-stashpop-deadlock-and-provider-fuse）成为无人认领的孤儿滞留数小时。同时 `Full scan failed: string indices must be integers` 当日出现 5 次，整轮扫描（含阻塞检测与 recovery）静默中断。同日姊妹变更 improve-run-lifecycle-governance 已覆盖活进程盲态/锁退避/假就绪巡检，本变更处理其未覆盖的事件投递与扫描韧性缺口。

## What Changes

- **同状态行动性更新的事件补发**：pm_engine 引起的"状态未变但语义需要行动"的重置（如 fix spec 重置回 ready、error 更新后重新可派发），必须保证对应 spec_ready 等 dispatch 路径被触达——事件要么由状态机补发，要么由 full_scan 恢复分支拾起，不允许静默丢弃。
- **bug-found 重发无害化**：periodic full_scan 对持续处于 bug-found 的父 spec 每轮无条件 re-trigger，其处理器会重置已有 fix 子 spec 为 ready 并清空跟踪字段。重发必须幂等且非破坏：子 spec 处于 ready/implemented/doing 类活跃或已完成态时不得降级其状态、不得清空 implementer_run/tester_run。
- **full_scan 崩溃根因修复与条目隔离**：定位并修复 `string indices must be integers` 崩溃点；单条 spec 处理异常只跳过该条并记日志，不中止整轮扫描；每轮扫描产出 handled/failed 统计日志。
- **孤儿 ready 恢复分支扩展**：full_scan recovery 对 ready spec 的跳过条件从「有 error 或有 implementer_run 即跳过」改为「存在存活 agent 子进程或有未超时的活跃派发才跳过」；带 error 的 ready 与有历史 run 记录但当前无活跃运行的 ready 均须触发重新派发。

- **验证终态语义校验**：agent_runner 对 rc==0 的 result 终止事件解析 is_error/subtype，错误类判失败并 raise，杜绝"API 错误包装成成功"假阳性。
- **verified 晋级完整性核对**：verifier 成功后、testing→verified 前核对进度 done>=total；不完整按失败重试处理。晋级路径 fail-closed。
- **VERIFIED 回退逃生门**：状态机允许 VERIFIED→TESTING（仅门禁自动路径），断点保留，消除死锁态。
- **run 产物生命周期保障**：attempt 结算前 runs jsonl 禁删、删除留痕（本日事故中关键证据文件消失）。

## Capabilities

### New Capabilities
- `spec-event-delivery-integrity`: 状态机同状态语义更新的事件补发契约与 bug_found 重发的幂等无害化约束
- `full-scan-resilience`: 全量扫描的单条隔离、崩溃根因防护与孤儿 ready 的恢复覆盖
- `verifier-judgment-integrity`: 验证终态语义校验、晋级前进度核对与 VERIFIED 回退逃生门

### Modified Capabilities

<!-- openspec/specs/ 当前为空，无既有活跃能力可修改 -->

## Impact

- **代码**：`.fenix/core/event_bus.py`（full_scan recovery 分支 L95–108、full_scan 异常包裹 L112–113）、`.fenix/core/pm_engine.py`（spec_bug_found 处理器的 fix-spec 重置逻辑、_on_spec_ready L108 起）
- **依赖**：improve-run-lifecycle-governance 实现后的 `has_live_attempt` / 锁重建接口若可用则直接复用做存活判定；不可用时以进程表 + run 文件 mtime 兜底实现（不重复造锁机制）
- **测试**：tests/test_core.py 相关用例扩展：同状态重置触达调度、连续扫描下 implemented 子 spec 不被降级、含异常条目的全量扫描完成并统计失败数、孤儿 ready（带 error / 带 implementer_run）两例均获重新派发
