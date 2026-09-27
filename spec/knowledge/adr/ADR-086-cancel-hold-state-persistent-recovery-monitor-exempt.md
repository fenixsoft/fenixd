# ADR-086：人工取消保持态跨重启持久，恢复/监测链路豁免

date: 2026-09-14
status: accepted

## Context

取消 hold-state 语义下 spec 停留 implementing/testing、run 字段保留，运行期防重派靠收尾分支早退。daemon 重启后该防线消失：恢复逻辑按 status 对 implementing 复位重派、对 testing 递增重验计数，人工取消决策被静默覆盖；监测面 stuck 检测同样覆盖保持态并自动升级 Administrator，Administrator 可能自行复位——「我来决定何时重派」的人工意图被自动链路代理破坏。

## Decision

- 保持态载体 = spec entry 布尔字段 `_cancelled_hold`，随 STATE.md 持久化、重启天然存活，与 `_retry_count` 等内部字段同层；不用独立标记文件——字段随 spec 生命周期，无孤儿清理问题，既有 update_spec/transition 写路径零新增。
- 全部 hold-state 收尾分支写入标记；重启恢复循环最前（status 分支判定之前）查标记，命中即跳过——不复位、不重派、不递增重验计数。
- 解锁唯一通道 = updates 显式含 `status` 键的 update_spec（admin 处置 / 面板重派 / freeze-unfreeze / 恢复逻辑自身），同步清标记；仅写 error 的隐式 updates 不清（取消收尾自身只写 error，自洽）。
- 自动监测对保持态豁免；人工决策在重启与监测两个面都不可被静默覆盖，只有显式复位动作可解除。
- 无标记的存量 spec 不迁移（保持既有行为），零回填成本。

## Consequences

- 取消保持 spec 长期滞留是有意等待态：无自动链路再打扰，继续时显式复位一步即可。
- 下划线内部字段族不外泄展示层，无新增展示面。
- 未来新增 run 类型必须核对新 hold-state 写点（spec 场景钉六处行为 + grep 核对任务），遗漏写点的保持态在重启后仍会被覆盖。
