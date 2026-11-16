# lane-stall-daily-aggregation

API 往返停滞的车道级日累计记账能力：把既有单 run 粒度的停滞观测升维到「车道×日」累计视角，供运营面当日感知 provider 拥塞。归属 fenixd 框架 agent_runner 观测链、self_review 聚合面与 admin_monitor 信号面。

## 术语

- 停滞（stall）：单次 API 往返等待超 60 秒（LATENCY_STALL_SECONDS 统计线），口径=tool_result→下一 assistant 配对间隔（既有官方口径不变）。
- 车道（lane）：run 的 agent_type 维度（planner-judge / planner-plan / admin 等）。
- 车道日累计：同一自然日（UTC）内同车道全部终态 run 的停滞总秒求和。

## 行为

1. 供数：latency_stats 输出含 latency_stall_total_seconds（超统计线样本求和）；run_metrics 终态行透传该键；三常量（统计线/期内告警线/分级线）同值不同义、禁止合并的既有约束保持。
2. 日汇总：self_review 停滞聚合按 agent_type 分组输出车道级日汇总行（总秒/run 数/最大单次/是否超阈值），在既有扫描一遍内完成、不新增 IO。
3. 阈值告警：admin_monitor 在 api-stall 收尾检测循环内维护车道×日累计计数器，超阈值发 info 级 signal；去重键=lane+date，同车道同日至多一条；信号文案含累计秒数与 provider 拥塞提示；阈值配置化（admin.lane_stall_warn_minutes，缺省 planner-judge 车道 30 分钟，0=关闭）。
4. 兼容：既有单 run 分级（classify_round_stall）与升级信号（api_round_stall_escalated，success 终态豁免）行为不变；缺新键的存量 run_metrics 行按 0 计，不回填。