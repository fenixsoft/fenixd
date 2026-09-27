<!-- knowledge: capability=stashpop-conflict-treatment rev=1 sources=spec/archive/2026-09-14-fix-mergeback-stashpop-silent-loss -->

# stash pop 冲突处置

stash pop 冲突自愈后的可见性与善后契约：admin 直发告警、被取代 stash 条目自动 drop，保证冲突处置可追溯且不误删有独有内容的条目。

## 现行规则

- 冲突自愈后直发 admin 告警：pop 冲突自愈完成（UU 清空、stash 条目保留或 drop）后，dispatch 层直接向 admin_alerts 追加一条 `signal_type: stash_pop_conflict` 的告警记录，不依赖 spec 的瞬态 error 字段或日志指纹风暴规则作为唯一通知渠道。`admin_monitor` 的 `STORED_SIGNAL_TYPES` 收录该类型（severity=major，recommendation 给核对指引）；告警 description 必含 spec 名、冲突文件清单、stash 条目去向（保留/drop + sha）、逐文件找回命令 `git show <sha>:<file>`（条目保留时）。spec.error 字段写入行为保持不变（向后兼容 dashboard 时间轴读侧）。
- 无冲突不产生告警：merge-back 的 stash pop 成功（conflict_files 为空）时不新增 `stash_pop_conflict` 记录，spec.error 保持 None。
- 被取代条目自动 drop：自愈完成后，若 stash 条目对全部冲突文件的内容与合并后 HEAD 完全一致（树级 `git diff --quiet <sha> HEAD -- <file>` 判定），该条目零独有内容，自动 drop；任一冲突文件存在差异则保留，告警 description 含该文件的找回命令。drop 前必须核对 stash sha 仍为栈顶（防并发 autostash 插队误删），sha 记入日志（gc 前可按 sha 找回）；非冲突文件的 stash 改动已在 pop 时回贴工作区，不参与判定；drop 与保留两种结局都必须在日志中明确记载。

## 溯源

- 史前复原（存量基线） — stash pop 冲突按三方合并自愈重建工作区改动，冲突处置不丢已实现内容
- 2026-09-14 fix-mergeback-stashpop-silent-loss — 固化 stash_pop_conflict 直发告警契约（白名单收录/description 内容清单）、被取代条目树级一致性自动 drop（栈顶钉住防线）与 merge 前 WIP 重叠预警（该预警后升级为执行级重叠闸门，现行语义见 merge-back 能力页）
