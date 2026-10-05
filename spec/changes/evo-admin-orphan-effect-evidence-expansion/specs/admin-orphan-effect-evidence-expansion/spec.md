## 能力：孤儿处置生效核查证据家族扩展

_orphan_group_effect_evidence 判定「处置已生效」的证据来源，从「当前日志尾部 256KB 的 blocked→X 手动解冻留痕」扩展为多家族并集，任一家族命中即视为生效并走既有补记收口路径。

### 需求

1. 日志对账覆盖轮转：证据检索文件集为 fenixd.log 与 fenixd.log.1.._LOG_ROTATION_BACKUPS（core/admin_monitor.py:166 常量，回退写法参照 :3449-3454 既有实现），按对账窗口 [组内最早 created-_ORPHAN_EFFECT_LOG_SLACK_SECONDS, now] 只消费时间戳落在窗内的行；mtime 早于窗口起点的文件跳过，单文件读取仍限尾部容量。
2. 动作家族扩展：除解冻 Transition 留痕外，新增两类仓库旁证——(a) merge-back 放行：对账窗口内存在合并目标分支的 merge commit；(b) 归档收尾：窗口内存在提交消息含目标 spec 名的收尾提交（如 ae3fe764「提交 fix-knowledge-backfill-reconstruction 归档删除收尾」形态）。
3. STATE 旁证：global 组的 spec 字段是占位符 "global"（core/admin_monitor.py:652 归一），须先从组记录 actions_taken/evidence 或关联 SIGNAL 记录中提取具体 spec 名，再回退 core/state_machine.read_one（:893）判 frozen/status；提取不到具体 spec 名时不启用该家族，不得猜测。
4. 家族命中后的收口路径不变：append_orphan_backfill（admin_store.py:919）+ mark_signal_handled（:600），幂等由 has_disposition_backfill（:900）保证。
5. 全部家族未命中时维持现状：fail-closed 升级，不新增自动豁免。
6. 机制 docstring 的「禁止记录自证」约束继续适用：新增证据家族同样只读外部痕迹（日志/git/STATE），不得以处置记录自身内容为生效证据。

### 验收

- 留痕在轮转文件中的组：核查命中并自动收口，不再升级。
- 治愈动作为提交/合并的组：对应家族命中并收口。
- 无任何证据的组：行为与现状一致（升级）。