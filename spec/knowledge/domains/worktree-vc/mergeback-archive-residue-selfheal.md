# merge-back 归档残留自愈与顺延链周期消费者
<!-- knowledge: capability=mergeback-archive-residue-selfheal rev=1
     sources=spec/archive/2026-10-13-evo-mergeback-archive-residue-selfheal -->

merge-back 因主树脏文件被拒进入顺延后的自愈兜底：熔断出口前置只读「归档残留」评估，命中即由框架代为补提交归档收尾并立即重放合并；熔断后的悬置条目另有周期消费者接手——自动放行先行，人工只处理确实无法自动收尾的形态。

## 规则

### 残留判据（只读）

- 评估插在 merge-back 顺延的熔断出口之前（顺延超宽限窗口或轮数达上限时先评估再决定熔断），全程只读、不改工作区。
- 归档残留判据：主树脏文件同时满足 `spec/changes/<spec>/` 下文件为删除态、`spec/archive/` 对应侧存在新增/未跟踪文件，且两侧**同 spec 名成对**（git 重命名行 R 天然成对）；任一脏文件不落在 `spec/changes` 与 `spec/archive` 两类路径即一票否决整条授权。
- 特征信号单源复用归档收口共享辅助（core/archive_commit.py，engine 的 `_archive_move_residue` 委托复用，禁两处各写一套特征）；该共享辅助自身是「任一侧即算残留」的宽判据，自愈授权必须另加两侧成对校验。
- 仅单侧的半提交形态（仅 changes 删除态、或仅 archive 新增侧）不授权自动收尾，落回既有熔断等人工——防把来历不明的 spec/changes 删除误当残留提交。

### 自动收尾与重放

- 判据命中：框架代为补提交归档收尾——`git add` 限定为共享辅助返回的**精确残留路径清单**（MUST NOT 退回 `git add -- spec` 或双前缀通配，防卷入其它 spec 在途草案），提交消息为 `[fenix] archive: <spec 名列表> 归档入库` 形态（与归档收口提交同形），随后立即重放既有 merge-back 路径；成功则清理 `_merge_retry_*` 记账正常收尾，零 admin 告警、零 Timer 排程。
- 补提交由重放成功的 merge-back push 携带入库；重放失败时留待后续 push（与归档自身自动收口同语义），不单独加推。
- 补提交前重查工作区：归档收口已被并发完成则跳过补提交、直接重放 merge。
- 单条 merge-back 的自动收尾至多尝试一次（进程内集合记账，daemon 生命周期语义，重启后至多再试一次），避免与归档自身重试互相踩踏。

### 熔断与留痕

- 收尾失败或重放再败：走既有熔断告警（`mergeback_spec_dir_inflight_stuck`），evidence 增补自愈评估摘要（判据命中与否、补提交 hash、失败原因），保持人工可见；同条目告警去重幂等不刷屏。
- 归档收口的 fail-open 语义不变：收口失败悬置的残留由本自愈在下次 merge-back 撞上时自动收尾；push 尾部收口兜底保留，双保险并存。
- 每次自愈评估（命中/未命中）落一条可检索日志；命中且成功的写告警留痕供台账消费。

### 周期消费者（顺延链兜底）

- daemon 主循环以 120 秒节拍复查 spec 目录顺延条目（无 `_wip_gate_deferred` 标志的车道），只接手「已超熔断阈值（与熔断出口同判式：宽限窗口或轮数上限）且仍 `_merge_retry_pending`」的条目，接手为 merge-only 重试或维持熔断降级。
- 未超阈值条目由 60 秒 merge-only Timer 链驱动，消费者必须跳过——一条顺延条目任一时刻至多一个驱动源；与存活 Timer 链同拍双驱动会让 git index.lock 竞争的失败被误计入顺延轮数、提前熔断。
- 带 `_wip_gate_deferred` 标志的条目归 WIP 消费者车道（见 [spec 车道 WIP 阻断延迟合回](wip-defer-merge-retry.md)），本消费者跳过。
- 消费者接手重试每条目至多一次（daemon 生命周期），失败维持既有熔断告警与人工通道，不无限节拍重试。

### 安全边界

- 自动触碰面恒限于共享辅助判定的精确残留路径（均落 `spec/changes` 与 `spec/archive` 两类路径）；绝不自动提交源码路径，非归档类脏文件（源码 WIP 等）维持现状顺延→熔断等人工。

## 溯源

- 2026-10-13 evo-mergeback-archive-residue-selfheal（spec/archive/2026-10-13-evo-mergeback-archive-residue-selfheal） — 新建本页：熔断出口前置归档残留只读评估（宽特征共享辅助 + 同 spec 两侧成对授权校验）、精确路径补提交 + merge-back 重放 + 单次尝试上限、熔断告警 evidence 增补自愈摘要、120 秒周期消费者接手超阈值条目（阈值分界防双驱动）
