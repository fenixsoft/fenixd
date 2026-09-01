# fix-startup-double-dispatch

## Why

**来源**：Administrator 处置 `fix-admin-run-blocks-mainloop`（2026-09-01）时定位到的框架调度竞态，实测已造成一整条 SPEC 链卡死 + 约一半实现 token 浪费。

**根因**：daemon 启动时存在两条派发路径（启动扫描 + 事件回放），`_on_spec_ready` 的防双派发守卫依赖 `has_active_worktree`（worktree 锁已注册）——但第一个 run 注册锁之前存在一个窗口，两条路径都能通过守卫，同一 spec 被连派两个 implementer。

**实测证据**（`.fenix/logs/fenixd.log` 行 33945 / 33962）：

```
12:15:06.857881Z  Running implementer for 'fix-admin-run-blocks-mainloop' (attempt 1/3)  run_id=impl-…-1788264906-a1
12:15:07.021230Z  Running implementer for 'fix-admin-run-blocks-mainloop' (attempt 1/3)  run_id=impl-…-1788264907-a1
```

两 run 相距 **164ms**，均为 attempt 1/3，各自建 worktree、各自完整实现一遍。

**后果链**（同一次事故的三段放大）：

1. **重复实现烧钱**：两个 implementer 各自跑完整实现（a2 分别 127 / 195 turns）；本链累计 45.47M input token（91% 预算），其中约一半烧在被丢弃的那份实现上。
2. **merge-back 失败覆写在飞验证态**：先完成者（4906）13:09:35 merge 进 main 并进入 testing、派出 verifier；后完成者（4907）13:15:29 merge-back 与 main 冲突，**无条件把 status 写回 ready**，覆写了在飞的 testing 态。
3. **验证结论被静默丢弃**：verifier 13:54:27 完成、5/5 场景通过，但此时状态已是 ready，`ready→verified` 与 `ready→done` 两次被判 `Invalid transition` 拒绝——验证成功只留下两行 ERROR 日志，spec 悬挂在 ready（error 被顺手清空）。随后 recovery 把「ready + 无 error」当孤儿重派 implementer，撞上已耗尽的实现预算 4/4，冻结 blocked 并升级人工——用户在 Dashboard 看到「为什么这个 spec 还是 ready」。

## What Changes

- **派发单飞（根因修复）**：`_on_spec_ready` 派发入口增加 per-spec 原子单飞标记（进程内 dispatch 注册表或 STATE.md 原子字段），同一 spec 的并发 `spec_ready` 处理只放行一个；单飞标记须在 worktree 锁创建**之前**占位，封死启动窗口。启动扫描与事件回放对同一 spec 的重复事件合并为一次派发。
- **状态回写保护（下游加固）**：merge-back 失败回写 ready 前，检查 spec 当前状态——若已在 testing/implemented 且存在活跃 tester run，不降级 ready，只记录冲突并待验证结束后统一处置（避免覆写在飞验证态）。
- **verifier 终态对账（下游加固）**：verifier 完成时若 spec 状态已非 testing，不得静默丢弃验证结论：按报告与状态机对账——结论为 pass 且实现已 merge 时重放合法迁移路径（implemented → testing → verified → done），否则落 blocked 并附证据，保证终态可達。
- **双派发可观测（可选）**：检测到同 spec 并行活跃 implementer run 时发 admin 信号，让 token 浪费可见而非静默发生。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `pm-engine`（调度）：`_on_spec_ready` 增加派发单飞去重；merge-back 失败与 verifier 完成的状态回写增加「活跃 run / 当前状态」前置检查。
- `event-bus`（调度）：启动扫描与事件回放对同一 spec 的重复 `spec_ready` 事件去重。

## Impact

- `core/pm_engine/engine.py`：`_on_spec_ready`（单飞守卫）、implementer 完成处理（merge-back 失败的条件回写）
- `core/pm_engine/verification.py`：verifier 完成处理（终态对账路径）
- `core/event_bus.py`：`_dispatch_changes` / 事件去重
- `core/state_machine.py`：可能需要新增单飞标记字段的解析/序列化（若走 STATE.md 方案）
- 测试：`tests/test_run_lifecycle_governance.py`（已有 live-attempt 守卫用例，需补启动窗口双派发、testing 中被覆写、verifier 终态对账三类用例）

## 验收口径

- 同一 spec 在 daemon 启动期只允许派发一个 implementer run（构造启动扫描 + 事件回放并发场景验证）。
- merge-back 失败不再把 testing 中（有活跃 tester run）的 spec 写回 ready。
- verifier 完成时无论 spec 处于何种被竞态改写的状态，验证结论都不丢失：要么推进终态，要么 blocked 带证据。
