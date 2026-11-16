# daemon-lifecycle Specification

## ADDED Requirements

### Requirement: 计划内排水窗不得被静默夹短

计划内重启的排水窗有效值 SHALL 按 min(run_drain_max_seconds, supervisor SIGKILL 等待−10s) 口径推导；配置一致性校验 SHALL 在有效值低于 agents.run_drain_max_seconds 申报值时输出含原始值与推导值的显式告警（不阻断启动）。缺省部署的有效排水窗 SHALL ≥300 秒。

#### Scenario: 一致性门拦截静默夹回

- **WHEN** 部署侧把 admin.shutdown_drain_seconds 覆盖为 0 而未同调 run_drain_max_seconds
- **THEN** 配置加载校验输出有效排水窗被夹短的显式告警并留痕，不阻断启动

### Requirement: 在飞维护车道响应重启 checkpoint 旗标

code-review 等无 spec 绑定车道的 run 主循环 SHALL 在波次边界读取重启 checkpoint 旗标（broadcast_restart_checkpoint 落位）；旗标置位时 SHALL 在当前波次收尾（分片落盘+终态抢救文件写毕）后退出，不得开启新波次。

#### Scenario: 排水窗内单波次收尾

- **WHEN** 悬空强制重启触发排水且旗标在 run 第 N 波次中途置位
- **THEN** run 完成第 N 波次分片落盘后自行退出，在排水窗内正常收场，不接收 SIGKILL

### Requirement: writeoff 锚即时续审

code-review 车道遗留的 writeoff 锚 SHALL 由独立周期扫描消费（不依赖每日周期函数），命中未核销锚即派发剃余续审；扫描 SHALL 保留夜窗顺延与单飞闸，且不受 last_run_date 同日防重闸拦截（锚在场证明当日未完成）。

#### Scenario: 被杀当日分钟级续审

- **WHEN** 全仓审查 run 被排水终止且 writeoff 锚在册
- **THEN** 周期扫描在下一 tick 内派发续审 run（manifest redispatch_of 指回被杀 run），覆盖空窗从次日调度节拍压缩到分钟级

### Requirement: 续审注记原因真实

writeoff 锚驱动的续审 run 档案注记 reason SHALL 记 writeoff_resume，不得复用 429 ratelimit 字面。

#### Scenario: 注记可对账

- **WHEN** 锚驱动续审派发落档案注记
- **THEN** reason=writeoff_resume 且与续审检索对账键一致