# Design: admin-awaken-inflight-claim-guard

## 判重键选型

维持 spec 单键宽口径（任意 signal_type），不收窄为 (spec, signal_type)：fix-admin-cross-type-duplicate-dispatch 已实证窄口径漏跨类型并发（core/admin_monitor.py:6370 注释在案）。人工通道豁免使合法并行（用户显式 invoke_manual vs 自动唤起）不受影响。

## 认领实现

- 进程内集合 _admin_dispatch_claimed_specs（threading.Lock 保护），键=spec 名。
- 登记点：_invoke_administrator 决定派发后、submit 前；复查顺序=先既有 pending 查询（_has_active_admin_run_for_spec）后认领集合查询，任一命中即让位。
- 释放点：core/agent_runner/maintenance_runs.py run_administrator worker 的 finally（成功、失败、异常三路统一）；daemon 重启清空由 store 侧 pending 记录与孤儿看护兜底（既有 fix-admin-self-heal 路径），认领不持久化。
- 备选（否决）：提交时预写 pending DISPOSITION——持久化更强但需处理派发失败与 daemon 中断的残留清理，复杂度不成比例；进程内认领加既有兜底已覆盖本缺口。

## 让位语义

复用 _persist_skipped_disposition（mutex-skip 形态）并 return False：调用方（摄取循环 core/admin_monitor.py:4271 分支与 _handle_signal :5928 分支）既有「未送达 → 不 mark_escalated → 下一巡检周期自然重评」语义原样生效；spec_amendment_inflight 的指纹备忘回滚（:1917）保证同修订集冷却期满可再成条。复活方向（deferred-resume 收口态重检）属升级链面，由在途 fix-escalation-chain-watchdog-yield-gaps 承接，本能力不重复建设。

## 风险与对策

- 认领泄漏（worker 异常未走 finally）→ finally 统一释放 + 孤儿看护超时兜底；泄漏期最长一个处置周期。
- 守卫误伤合法并行 → 守卫面仅限自动唤起通道；invoke_manual 与 arbiter 单飞不在守卫面，测试显式断言。
- 排队时延根因（共享池 max_workers=2 与 code-review checkpoint 共池）不在本能力范围，本能力仅消除其竞态后果。