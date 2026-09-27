<!-- knowledge: capability=admin-reset-error-escalation rev=1 sources=spec/archive/2026-09-20-add-control-plane-silent-failure-guards -->

# 复位路径编程错误升级

AdminMonitor 复位路径（`_reset_env_blocked_after_disposition` 及同类）的异常分层：代码缺陷升级人工，运维异常仅记录。

## 现行规则

- 异常分层：`TypeError`/`AttributeError`/`NameError` 三类代码缺陷走升级路径，落 `kind=escalation`、`signal_type=admin_reset_programming_error`、`severity=critical` 的告警，description 含异常类型；其余异常（`OSError`/网络类等运维失败）保持 WARNING 记录语义，不升级。
- 升级告警内容：携带 spec、severity=critical、reset_path、signal_type（原信号类型）、异常类型与消息，以及调用点（`core/` 内最深栈帧的「文件:行 (函数名)」），工程侧无需复现即可定位；告警经 `alert_lifecycle.attach_trigger` 埋点，与既有 escalation 通道一致。
- 不重抛：升级路径不重抛异常，处置记录先落盘的右关联设计不被破坏——复位失败不回滚已落盘的处置记录；升级告警落盘本身失败时只记日志，不再抛出。
- 去重：同一 (spec, admin_reset_programming_error) 已有未处理告警时，后续巡检跳过重复落盘（`unhandled_for` 去重），不逐轮堆积同型告警。
- 信号表登记：`SIGNAL_SEVERITY` 登记 `admin_reset_programming_error: critical`；`SIGNAL_RECOMMENDATION` 登记处置指引——这是代码缺陷，Administrator 无法修复，须工程侧定位修正，勿派子 fix 反复重跑。

## 溯源

- 2026-09-20 add-control-plane-silent-failure-guards — 复位路径异常分层（编程错误升级/运维异常静默）、调用点可定位证据、不重抛与未处理去重
