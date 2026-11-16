# Design: admin-awaken-inflight-claim-guard

## 判重键选型

维持 spec 单键宽口径（任意 signal_type），不收窄为 (spec, signal_type)：fix-admin-cross-type-duplicate-dispatch 已实证窄口径漏跨类型并发（core/admin_monitor.py:6370 注释在案）。人工通道豁免使合法并行（用户显式 invoke_manual vs 自动唤起）不受影响。

## 认领实现

- 进程内集合 _admin_dispatch_claimed_specs（threading.Lock 保护），键=spec 名、值=属主令牌（登记时生成、随派发上下文携带）。
- 登记点：_invoke_administrator 决定派发后、submit 前；复查顺序=先既有 pending 查询（_has_active_admin_run_for_spec）后认领集合查询，任一命中即让位；认领集合判定与登记须同一锁临界区原子完成（防两派发线程各自过判再登记互漏）；先登记后 submit，submit 抛出即同锁回滚。
- 复查前置门（评审补定）：仅自动通道（signal_rec 非空）且 signal["spec"] 非空才复查——invoke_manual 以 signal_rec=None 直调本函数（core/admin_monitor.py:8221）须豁免；spec=None 时 _spec_has_active_admin_run 的 spec 过滤被 None 哨兵禁用（:6685-6690），daemon 级信号不复查。
- 释放点：core/agent_runner/maintenance_runs.py run_administrator worker 的 finally（成功、失败、异常三路统一），按令牌匹配删除（不匹配 no-op）——run_administrator 为人工通道与同步回退共用，按键无条件删除会误放他属认领。跨模块接线用惰导入（先例：core/agent_runner/runner.py:9526 惰导入 core.admin_monitor._error_fingerprint、maintenance_runs.py:493 惰导入 AdminStore），MUST NOT 模块级导入（admin_monitor → agent_runner 为既有依赖向，反向模块级导入成环）。
- 存活界（评审修正）：认领集合为进程内存态，daemon 重启即清、不持久化；孤儿看护对象是 store 内 pending DISPOSITION 记录，与认领集合无交集——不承担（也无从承担）认领兜底，泄漏面以进程生命周期为界，finally 统一释放即闭环。
- 备选（否决）：提交时预写 pending DISPOSITION——持久化更强但需处理派发失败与 daemon 中断的残留清理，复杂度不成比例；进程内认领加既有兜底已覆盖本缺口。

## 让位语义

复用 _persist_skipped_disposition（mutex-skip 形态）并 return False：调用方（摄取循环 core/admin_monitor.py:4271 分支与 _handle_signal :5928 分支）既有「未送达 → 不 mark_escalated → 下一巡检周期自然重评」语义原样生效；spec_amendment_inflight 的指纹备忘回滚（成条时预写、未送达回滚：core/admin_monitor.py:5116-5122、:6059-6063；让位路径 return False 即走该既有回滚链）保证同修订集冷却期满可再成条。复活方向（deferred-resume 收口态重检）属升级链面，由在途 fix-escalation-chain-watchdog-yield-gaps 承接，本能力不重复建设。

## 风险与对策

- 认领泄漏（worker 异常未走 finally）→ finally 统一释放；认领集合进程内存态、daemon 重启即清，孤儿看护不承担（也无从承担）认领兜底——泄漏面以进程生命周期为界。
- 守卫误伤合法并行 → 守卫面仅限自动唤起通道；invoke_manual 与 arbiter 单飞不在守卫面，测试显式断言。
- 排队时延根因（共享池 max_workers=2 与 code-review checkpoint 共池）不在本能力范围，本能力仅消除其竞态后果。