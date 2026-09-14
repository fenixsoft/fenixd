## Why

merge-back 的 stash pop 冲突自愈（fix-stashpop-deadlock）目前只把冲突文件清单写进 spec 的瞬态 error 字段并记一条 ERROR 日志：spec 下轮合并成功即清空 error，单次 ERROR 又够不着 daemon_errors 的「10 分钟 3 次同指纹」风暴门槛，导致 2026-09-07 三次冲突事件在 admin_alerts.json 零记录、无人被通知，被丢弃的主树 WIP 改动只能靠日志偶然发现。同时 stash 条目一律保留，其中内容已被 HEAD 完全取代的条目（三次事件中已核实两次被取代、一次经 config 通道达成意图）永远等不到清理，75 条 fenix autostash 在主树常年脏时无限期滞留。

## What Changes

- pop 冲突自愈完成后，由 dispatch 层直接向 admin_alerts 写入一条 `stash_pop_conflict` 告警（复用 admin_store.append 管道），通知不再依赖瞬态 error 字段或日志指纹风暴；告警文本含冲突文件清单与逐文件找回命令
- pop 冲突自愈后自动核对：对每个 UU 文件比较 stash 版与合并后 HEAD 版（树级 diff），全部相同 → stash 条目零独有内容，按 fix-autostash-conflict-loop（4f753ed）既有的「sha 仍在栈顶才 drop」模式自动 drop 并留痕；任一不同 → 保留条目并在告警中给出 `git show <sha>:<file>` 找回指引
- merge-back 预演闸放行后、stash 之前，检测「分支改动文件 ∩ 主树脏 tracked 文件」重叠，非空则记 WARNING 并把重叠清单挂到 MergeConflictInfo，由 dispatch 并入告警文本，冲突发生前给出预警

## Capabilities

### New Capabilities

- `stashpop-conflict-treatment`: merge-back stash pop 冲突的可视化告警、被取代条目的自动 drop 判据、以及冲突前的 WIP 重叠预检

### Modified Capabilities

（无——归档能力 mergeback-stashpop-self-heal 的行为扩展，活跃能力区无 stash 相关 spec）
