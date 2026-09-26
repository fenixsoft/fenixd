# spec：stale-code-selfheal-noise-control

## ADDED Requirements

### Requirement: 自愈健康路径告警降级

当 stale_code_selfheal.enabled 且自愈链路健康（自愈重启请求成功发出并生效）时，系统 SHALL 将陈旧代码告警以 info 级写入 admin_alerts.json（kind 非 escalation、severity 为 info），并 SHALL 在日志输出含当日累计次数的日计数；该类记录 SHALL 继续受 60 分钟去重约束，SHALL NOT 进入人工告警队列与升级路径，且 SHALL NOT 依赖 mark_handled 生命周期（该接口仅锚定 ESCALATION）。

#### Scenario: 自愈启用且重启成功

- WHEN stale_code_selfheal.enabled 且 daemon 因陈旧代码成功触发自愈重启
- THEN 本轮 stale_code 告警以 info 级 kind 写入存储，severity 为 info，附当日累计计数
- THEN 该记录不出现在 pending_escalations 同口径（kind=ESCALATION 且未处理）清单中

#### Scenario: 自愈禁用、失败或悬空超限

- WHEN 自愈被禁用、自愈动作失败、或陈旧悬空超过 max_dangling_seconds
- THEN 告警仍以 kind=escalation 写入并走既有升级路径，与 evo-add-stale-code-dangling-deadline 的升级口径对齐，不双重升级

### Requirement: 空闲确认缺省合并批次

stale_code_selfheal.idle_confirm_seconds 缺省 SHALL 为 600 秒；项目级配置覆盖 SHALL 继续优先生效且热更新语义不变。

#### Scenario: 开发日密集落地

- WHEN 开发日多批代码在短间隔内相继落地且 daemon 持旧代码
- THEN 仅当连续空闲达 600 秒时触发一轮自愈重启，密集批次不再被逐个放大为多轮重启

#### Scenario: 项目显式覆盖

- WHEN 项目 config.yaml 设置 stale_code_selfheal.idle_confirm_seconds
- THEN 覆盖值优先生效，行为与现语义一致