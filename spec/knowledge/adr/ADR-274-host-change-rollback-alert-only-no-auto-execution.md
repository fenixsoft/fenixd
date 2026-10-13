# ADR-274：宿主变更回滚义务只告警不自动执行

date: 2026-10-13
status: accepted

## Context

agent（implementer/administrator）在 run 中可能对宿主系统级资源做变更（内核模块、dkms、系统包、设备节点）。2026-10-05 potplayer-base 事故中实现者以 dirty 版内核模块覆盖宿主 updates/dkms 正版且零备份，管理员写好的 pristine 重建修复计划随 run 被 600 轮击杀而未执行，污染持续在位。取证要点：击杀类终止（超时/轮次上限/判停 SIGKILL）没有 run-result 文件，worktree 拷回同样不发生——任何只依赖 run 结果收尾汇总的义务记录都会随击杀一起丢失。是否让框架在失败终态自动执行回滚（rmmod/depmod/modprobe/包还原）？共享宿主上属越权高危：run 前基线不可靠判定（无法确证变更是本 run 引入）、内核模块可能被并发 run 或系统服务占用（EBUSY 误伤）、回滚自身失败无兜底。

## Decision

- 回滚义务的权威载体=「变更发生时即时写入 worktree 根 host_changes.json」的登记文件；run 结果中的 host_changes 汇总只是收尾冗余（result-bearing run 两处一致），不作为义务依据。
- run 失败终态（error/killed，含无 run-result 的击杀类终止）且登记非空时，框架在 runner 终态记录点（先于 worktree 清理）读取登记文件，向 admin 告警通道派发「回滚义务」告警；告警只增不执行，回滚执行交维护者/admin 人工裁决。成功终态仅留痕不告警。
- 后续任何「框架自动执行宿主回滚/自动快照还原」方向必须显式 supersede 本裁定，并论证 run 前基线判定、并发占用互斥、回滚失败兜底三前提成立。

## Consequences

- 修复义务不随 run 击杀与 worktree 清理丢失（派发后 worktree 整目录删除告警仍存活），但回滚时效取决于人工消费告警的速度。
- 框架对宿主系统保持零写手：自动回滚执行器被排除在默认实现空间之外，自动全量系统快照同样不做。
- 代价是无宿主变更的 run 也须经过一次登记文件存在性检查（缺省不存在即跳过，零实质开销），且宿主实际修复依赖人工响应，存在窗口期。
