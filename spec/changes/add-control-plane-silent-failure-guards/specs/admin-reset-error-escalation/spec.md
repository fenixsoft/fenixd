# 复位路径编程错误升级（admin-reset-error-escalation）

## 需求

### R1 编程错误与运维失败分层
- `AdminMonitor._reset_env_blocked_after_disposition`（及同类复位路径）的异常处理 SHALL 分层：`TypeError`/`AttributeError`/`NameError` 三类**代码缺陷** MUST 走升级路径；其余异常保持既有 `WARNING` 记录语义，MUST NOT 升级。

#### Scenario: 编程错误升级
- **WHEN** 复位路径调用抛出 `TypeError`（如实参数量不符）
- **THEN** 落一条 `kind=escalation`、`signal_type=admin_reset_programming_error`、`severity=critical` 的告警，且 `description` 含异常类型

#### Scenario: 运维异常不升级
- **WHEN** 复位路径调用抛出 `OSError`/网络类异常
- **THEN** 只记 `WARNING`，不产生 `admin_reset_programming_error` 告警

### R2 升级告警内容
- 升级告警 MUST 携带：`spec`、`severity=critical`、`reset_path`、`signal_type`（原信号类型）、异常类型与消息，以及**调用点**（`core/` 内最深栈帧的 `文件:行 (函数名)`），供工程侧无需复现即可定位。
- 告警 MUST 经 `alert_lifecycle.attach_trigger` 埋点（与既有 escalation 通道一致）。

#### Scenario: 调用点可定位
- **WHEN** 编程错误经多层调用抛出
- **THEN** 升级告警 evidence 中的调用点为 `core/` 内抛错位置（文件:行），而非测试或框架外层

### R3 不重抛与去重
- 升级路径 MUST NOT 重抛异常：处置记录（disposition）先落盘的右关联设计不被破坏——复位失败不得回滚已落盘的处置记录。
- 升级告警落盘本身失败时 MUST 只记日志，不得再抛。
- 同一 `(spec, admin_reset_programming_error)` 已有未处理告警时，后续巡检 MUST 跳过重复落盘（`unhandled_for` 去重），避免每轮巡检堆积同型告警。

#### Scenario: 不重抛保证处置记录完整
- **WHEN** 复位路径抛编程错误且处置记录已落盘
- **THEN** `_reset_env_blocked_after_disposition` 正常返回（不抛），处置记录仍在 store 中

#### Scenario: 重复告警去重
- **WHEN** 同一 spec 连续两轮巡检各触发一次同类编程错误
- **THEN** 仅落一条未处理告警

### R4 信号表登记
- `SIGNAL_SEVERITY` MUST 登记 `admin_reset_programming_error: critical`；`SIGNAL_RECOMMENDATION` MUST 登记对应处置指引（指明这是代码缺陷、Administrator 无法修复、须工程侧定位修正、勿派子 fix 反复重跑）。

#### Scenario: 处置指引到位
- **WHEN** 告警落盘
- **THEN** `recommended_action` 非空且指明为代码缺陷而非环境问题

## 验收标准
- 单元测试：`TypeError` 注入 → 恰好 1 条 critical 升级告警；`OSError` 注入 → 0 条升级告警。
- 单元测试：拔牙验证（移除分层 except）→ 测试失败；恢复 → 通过。
- 回归：事故根因调用点 `handle_event("spec_implemented", spec, spec_entry)` 实参数量与生产签名一致（由 `callsite-arity-guard` 与既有测试共同钉住）。
