## 能力：merge-back 归档残留自愈与顺延链周期消费者

merge-back 因主树脏文件被拒进入顺延时，先做归档残留识别与自动收尾，识别不命中或收尾失败才熔断；顺延中的条目另有周期消费者兜底。

### 需求

1. 残留判据（只读）：工作区状态同时满足——spec/changes/<某 spec>/ 下文件为删除态，且 spec/archive/ 对应侧存在新增/未跟踪文件（复用 engine 的 _archive_move_residue 特征，core/pm_engine/engine.py:2941）；任一脏文件不落在 spec/changes 与 spec/archive 两类路径即判非归档残留。
2. 自动收尾：判据命中时由框架代为补提交归档收尾——git add 限定 spec/changes 与 spec/archive 路径，提交消息沿用归档收尾形态并含目标 spec 名，随后立即重放既有 merge-back 路径；全程写日志与告警留痕（补提交 hash、重放结果）。
3. 收尾失败或重放再败：走既有熔断（_report_mergeback_spec_dir_inflight_stuck，core/pm_engine/dispatch/rollback.py:553），evidence 增补自愈评估结果（判据命中与否、补提交 hash、失败原因），保持人工可见。
4. 周期消费者：仿 _recheck_wip_deferred_merges（core/pm_engine/dispatch/queue.py:2870，120 秒节拍）为无 _wip_gate_deferred 标志的 spec_dir_inflight 顺延条目建周期复查——60 秒 Timer 链因重启等中断后，周期消费者接手重试或按 spec_dir_inflight_grace_minutes（:2626）窗口降级，消除「熔断即无人接手」。
5. 安全边界：自愈只允许触碰 spec/changes 与 spec/archive 路径；单条 merge-back 的自动收尾至多尝试一次，避免与归档自身重试互相踩踏；补提交前重查工作区（收口已被他人完成则跳过补提交直接重放 merge）。
6. 观测：每次自愈评估（命中/未命中）落一条可检索日志，命中且成功的写告警留痕供台账消费。

### 验收

- 构造归档半程主树 + 待 merge-back 分支：不产生 admin 会话，自动收尾后合并成功，留痕含补提交 hash。
- 构造源码 WIP 脏文件：行为与现状一致（顺延→熔断）。
- Timer 链缺失（模拟重启后 pending 残留）：周期消费者在节拍内接手。