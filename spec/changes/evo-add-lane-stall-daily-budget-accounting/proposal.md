# add-lane-stall-daily-budget-accounting

## 背景与动机

判定/出题车道的 API 往返停滞（单次往返超 60 秒）单日累计约 101 分钟（6087.6s / 21 run / 56 次），其中 planner-judge 车道 10 个 run 全部中招、停滞占该车道总墙钟 44.8%（2996.9s/6695.4s）——外因上游拥塞（唯一 provider bigmodel.cn glm-5.3-flash，无替代通道）把判定收敛拉长近倍。停滞全部被编排层吸收（31/31 run 成功、0 超时 0 秒挂、升级信号 0 条），损失形态是墙钟税而非报废；且非偶发：3 个活跃窗停滞总量 10595.7s→9287.7s→6087.6s，评审车道历史上连续 7 窗停滞。

框架已有单 run 粒度停滞观测（归档 SPEC evo-api-stall-signal-grading 的分级 + run_metrics 终态行 latency_rounds/latency_stalls/latency_max），但车道级日累计与阈值告警不存在：self_review 摘要只出逐 run 行，provider 拥塞要等次日自省才被人工读到；run_metrics 无停滞总秒键。

## 目标

1. 停滞总秒供数：latency_stats 补 latency_stall_total_seconds 键，run_metrics 终态行透传。
2. 车道级日累计汇总：self_review 停滞聚合按 agent_type 分组出车道级日汇总行（停滞总秒/run 数/最大单次）附阈值标注，同一遍扫描零额外 IO。
3. 车道日累计阈值告警：admin_monitor 增加「车道×日」累计计数器，超阈值发 info 级 signal 提示 provider 拥塞，去重键=lane+date（每车道每日至多一条）。

## 非目标

- 不做 provider 拥塞治理/重试改造（外因，且停滞已被编排层吸收）。
- 不做 run 墙钟预算的停滞单列（需穿透 _run_agent 返回值→车道收尾→supervision 判定链，成本中等，拆独立立项）。
- 不做 dashboard provider 健康面停滞曲线（新建数据面+UI，缓办）。
- 不改变现有单 run 分级行为（classify_round_stall 与 api_round_stall_escalated 语义保留）。

## 交付物

core/agent_runner/latency.py（latency_stats 补总秒键）、core/agent_runner/runner.py（run_metrics 透传）、core/self_review.py（车道级日汇总）、core/admin_monitor.py（车道×日累计告警）、tests/test_lane_stall_accounting.py（单测）。

## 验收标准

- run_metrics 终态行含 latency_stall_total_seconds 且与样本求和一致；无停滞 run 为 0；两条透传链（_metrics_latency 与成功路径）均落新键。
- 自省摘要出现按 agent_type 分组的车道级日汇总行，含阈值标注。
- 同一车道同日多次超阈值只发一条 info signal（lane+date 去重）；daemon 重启后当日计数可从已落账 run_metrics 行重建；单 run 升级信号行为不回归。