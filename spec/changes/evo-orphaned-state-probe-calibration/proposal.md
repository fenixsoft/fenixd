# orphaned-state-probe-calibration

## 背景与痛点

防线四 orphaned_state 无驱动探测（c07475ff 合入）上线首日即误报：对 repair run 活跃推进期间的 spec 判定「无驱动」。根因是 run_id 前缀归一表 `_RUN_PREFIXES`（core/admin_monitor.py:262）缺 `repair-`，导致 `_spec_from_run_id("repair-...")` 返回 None，活跃的 repair run 文件在 `_has_recent_spec_run` 中不可见。同事件中派发的 Administrator 处置 run 以 Exit code 1 失败，失败原因无任何日志。

## 目标

- 修复前缀归一：repair- 前缀参与 run 文件活跃度判定，杜绝「活跃 run 被判定无驱动」类误报。
- admin/处置 run 非零退出补错误日志：捕获 CLI stderr 与退出上下文，失败可定位。
- 校准「三条件」判定语义与告警去重表述，避免同信号生命周期记录被误读为重复告警。

## 非目标

- 不改变 orphaned_state 的三条件判定结构（无活动 run/无存活子进程/无待派发）。
- 不改变 15 分钟短阈值与 stuck 160 分钟阈值的既有语义。