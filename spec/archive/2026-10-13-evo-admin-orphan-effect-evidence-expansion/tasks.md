## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_admin_orphan_disposition_effect_check.py
  kind: modify
```

## 1. 落地校验

- [x] 1.1 core/admin_monitor.py：_read_recent_unfreeze_transitions（:4713）日志源扩为 fenixd.log + fenixd.log.1.._LOG_ROTATION_BACKUPS 候选集，按对账窗口 [最早 created-_ORPHAN_EFFECT_LOG_SLACK_SECONDS, now] 过滤（mtime 剪枝 + 窗内行截取），单文件尾部限量语义不变。
- [x] 1.2 core/admin_monitor.py：_orphan_group_effect_evidence（:4656）global/None 分支新增证据家族——(a) merge-back 放行/归档收尾提交（git log 窗口内提交消息匹配目标 spec 名）；(b) 从组记录 actions_taken/evidence 提取具体 spec 名回退 core/state_machine.read_one 判 frozen/status，提取不到、或提取到的 spec 在 STATE 无条目/读取失败则按无证据跳过该家族；任一家族命中即走既有 append_orphan_backfill + mark_signal_handled 收口，全未命中维持 fail-closed 升级。

## 2. 测试

- [x] 2.1 tests/test_admin_orphan_disposition_effect_check.py：新增四类用例——解冻留痕在轮转文件（fenixd.log.1）中的组自动收口；治愈动作为收尾提交/分支合并的组经提交家族收口；spec 名可提取时 STATE 旁证收口、不可提取或 STATE 无条目/读取失败时跳过；三家族全空时仍升级且不假闭环；提交消息假阳性不误判。