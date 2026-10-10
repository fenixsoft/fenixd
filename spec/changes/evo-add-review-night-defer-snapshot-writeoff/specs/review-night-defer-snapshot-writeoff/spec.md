# review-night-defer-snapshot-writeoff

## ADDED Requirements

### Requirement: 静默窗支持多窗配置

系统 SHALL 支持把 `admin.code_review_fix.night_quiet_window` 配置为多个「HH:MM-HH:MM」区间（逗号分隔），并把单窗字符串按既有语义解析为单元素列表；空串/off 仍表示完全禁用；含非法片段的配置整体按无窗处理并 WARNING 一次（沿既有「一次」纪律）。

#### Scenario: 多窗配置下命中第二窗

- 本地时刻 04:20，配置 `03:00-03:15,04:15-04:45`
- code-fix 派发守卫与 admin 避让均返回窗内命中，下一可投递时刻为 04:45

#### Scenario: 单窗配置行为不变

- 配置 `04:15-04:45`，本地时刻 04:20
- 行为与多窗化之前逐字节一致

### Requirement: 周期审查派发跨窗顺延

周期代码审查检查点在派发前 SHALL 以「派发时刻 + 近几轮 code-review run 实测时长估计」得预计结束时刻；预计区间与任一静默窗相交时本轮不派发、不写同日防重状态、单飞标志 SHALL 复位（对齐空 manifest 分支既有复位口径——标志滞留会使后续巡检恒命中 already_running 而静默停摆），仅留日志（reason=night_quiet_window_deferred），窗末后的首轮巡检自然重新触发。无有效时长样本时回退为仅判派发时刻是否落窗。

#### Scenario: 01:00 起跑预计压窗即顺延

- run_at=01:00，近三轮实测时长均值 118 分钟，预计结束 03:00 后，与多窗之一相交
- 检查点返回 reason=night_quiet_window_deferred，当日状态文件不写入，窗末后巡检正常派发

#### Scenario: 无样本回退仅判派发时刻

- 归档无 code-review run_metrics 可读
- 仅当派发时刻本身落窗才顺延，行为不劣化于现状

### Requirement: scheduled 全仓轮具备核销资格

run_code_review 收尾的核销分支 SHALL 在「manual_full」之外对「scheduled 且全仓收集（window_start=None）」的 run 放行；解锁门仍为既有累计覆盖 ⊇ 完整 manifest 判定，manifest 缺失/损坏/判定异常一律维持锁定（宁锁勿白洗）；窗口档 scheduled run（window_start 非空）与一切 error 收场仍绝不核销。

#### Scenario: 抢救补齐后下轮解锁核销

- 上一轮 error 收场抢救落账（覆盖不全，核销锁定）
- 下一轮 scheduled 全仓 run 成功且累计覆盖 = 完整 manifest，observed 指纹非空
- 未再观测到的 open 条目置 resolved，pending-writeoff 锚清除，完成行 resolved>0

#### Scenario: 部分覆盖继续锁定

- scheduled 全仓 run 成功但 agent 静默少审（累计覆盖 < manifest）
- 核销锁定，WARNING 留痕，open 条目不动

### Requirement: 抢救落账留 partial 痕

error 收场抢救 inserted 或 updated > 0 时，系统 SHALL 写 pending-writeoff 锚文件（含 run_id、inserted/updated、时刻）于台账目录，并在其后任一 run 完成全仓核销或覆盖完整成功收尾时清除；锚存在期间，审查完成日志 SHALL 标注部分覆盖待核销态。

#### Scenario: 抢救写锚

- run 中途死于 api_error，抢救 inserted=92
- 台账目录出现 pending-writeoff 锚，完成日志含部分覆盖标注

#### Scenario: 核销后清锚

- 锚存在，后续 scheduled 全仓 run 覆盖完整并执行核销
- 锚文件清除，日志不再报待核销态