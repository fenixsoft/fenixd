# Design: fix-dispatch-orphan

## Context

fenixd 调度管线存在三条互相放大的失效路径（2026-08-27 事故实证，证据见 `.fenix/logs/fenixd.log`）：

1. **事件只看状态差**。`event_bus._dispatch_changes`（core/event_bus.py L168–192）仅当新旧 status 不同才生成事件；pm_engine 通过 state_machine 写回的同状态更新（如 fix spec 从 ready 重置为 ready、清空 implementer_run/tester_run）不产生任何事件，调度从此对它失明。
2. **bug_found 无条件重发**。full_scan 的 recovery 分支对每个持续 bug-found 的父 SPEC 每轮 re-trigger `spec_bug_found`（event_bus.py L102–104）；其处理器发现 fix 子 SPEC 已存在时执行"重置为 ready + 清空跟踪字段"，把已 implemented 甚至进行中的子 SPEC 打回原形。
3. **recovery 分支的孤儿盲区与扫描崩溃**。ready 恢复仅覆盖「无 error 且无 implementer_run」的 spec（event_bus.py L95–99）；带 error（所有重置路径都会写 error 字段）或有历史 run 记录的一律跳过。而 full_scan 整体被一个 try 包裹，当日出现 5 次 `Full scan failed: string indices must be integers`，一次崩溃使阻塞检测与全部 recovery 静默中止。

姊妹变更 improve-run-lifecycle-governance（实现中）覆盖：活进程探测 has_live_attempt、worktree 锁进程表重建、派发锁退避、假 ready 巡检。本设计复用其接口而不重复造轮子。

## Goals / Non-Goals

**Goals:**
- pm_engine 引起的行动性同状态更新必定触达 dispatch 路径
- bug_found 重发幂等且永不降级活跃/已完成子 SPEC、不清空其跟踪字段
- 单条 spec 异常不影响整轮 full_scan；`string indices must be integers` 根因修复
- 带 error / 带历史 run 记录的孤儿 ready 能被恢复分支重新派发

**Non-Goals:**
- 不改动事件循环架构（仍是 checksum 轮询 + 周期全量扫描）
- 不处理活进程盲态、超时监督、派发退避（归 improve-run-lifecycle-governance）
- 不改 dashboard 与 STATE.md 格式

## Decisions

- **D1 事件补发放在调用方而非状态机。** 同状态行动性重置由 pm_engine 在写回后直接调 `_on_spec_ready(spec)`（pm_engine.py L105 已有先例：启动路径即直调），不走 event_bus 事件比较。理由：状态机保持"纯记录"，避免为 diff 语义引入副作用的隐藏耦合；直调路径已验证可行。备选"让 _dispatch_changes 对带 action 标记的 update 也发事件"——需要跨层传递元数据且易漏标记，放弃。
- **D2 bug_found 重发加幂等守卫与字段保护。** 处理器现有 `already in progress — skipping` 判定扩展为三档：fix 子 SPEC 处于 drafted→implementing 等推进态或 implemented/tested 类态时仅记日志不动状态；处于 done/pushed 时完全跳过；仅在确认无活跃工作且从未成功派发过（implementer_run 为空且非本次新触发）时才保留现有 reset 行为，且 reset 不再清空 implementer_run/tester_run 历史值。理由：该字段的唯一用途是排队去重与诊断，清空制造的问题远大于收益。
- **D3 crash 根因：STATE.md 并发半写读取。** `string indices must be integers` 在 verify 门禁写入窗口同步出现，推断 read_all() 在半写瞬间把 dict 条目读成字符串后在 recovery 循环里做 `entry.get()` 触发 TypeError。修法：read_all() 解析层过滤/规范化非法条目并记 warning（防御在源头）；recovery 循环每条独立 try/except；full_scan 末尾输出 handled/failed 统计日志。实现阶段 MUST 先用最小复现（构造半写状态的 STATE.md 输入）证实根因假设再落防御，若证实为其他点位则按实际点位修复并在 PR 说明。备选"给 STATE.md 写入上文件锁"——锁已在部分平台不可靠且改动面大，列为后备。
- **D4 孤儿 ready 恢复：存活判定反转为白名单。** 跳过条件从「有 error 或有 implementer_run」改为「存在存活 agent 子进程 或 有未超时的活跃 worktree 锁」。可用时调用 improve-run-lifecycle-governance 的 `has_live_attempt`/`refresh_locks()`；其未落地期间用兜底：pgrep 匹配 `.claude/worktrees/{impl,verify}-<spec>-*` 的 claude 进程 + run 文件 mtime < 120 秒。重派发前清 error 字段但保留 implementer_run 作为历史记录（配合 D2 防清空）。理由：原条件把"曾经失败过"误当成"正在工作"；白名单反转直接消除两类孤儿的共同成因。

## Risks / Trade-offs

- [D1 直调可能双重排队] → `_on_spec_ready` 内部已有队列去重逻辑，补测试覆盖同状态重置后恰好又收到真实 spec_ready 事件的序列
- [D2 保留历史 implementer_run 改变字段语义] → 全局 grep 该字段的消费点确认均为"最后已知 run id"用法后实施；dashboard 展示不受影响（值为 null 时本就兼容）
- [D3 根因假设若不成立] → 设计要求先复现再修复，防伪根因；最小复现作为测试用例入库
- [整体与本枚举之外的孤儿成因共存] → 恢复统计日志（handled/failed）暴露残余问题，不为未知情况增加兜底分支

## Migration Plan

普通代码变更，随 daemon 重启生效。回滚 = revert 提交重启。无数据迁移。

## Open Questions

- 无
