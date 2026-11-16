# lane-stall-daily-aggregation

API 往返停滞的车道级日累计记账能力：把既有单 run 粒度的停滞观测升维到「车道×日」累计视角，供运营面当日感知 provider 拥塞。归属 fenixd 框架 agent_runner 观测链、self_review 聚合面与 admin_monitor 信号面。

## 术语

- 停滞（stall）：单次 API 往返等待超 60 秒（LATENCY_STALL_SECONDS 统计线），口径=tool_result→下一 assistant 配对间隔（既有官方口径不变）。
- 车道（lane）：run 的 agent_type 维度（planner-judge / planner-plan / admin 等）。
- 车道日累计：同一自然日（UTC）内同车道全部终态 run 的停滞总秒求和。

## ADDED Requirements

### Requirement: 停滞总秒供数

latency_stats MUST 输出 `latency_stall_total_seconds` 键（对超 LATENCY_STALL_SECONDS 统计线的样本求 sum；空样本 / 无停滞 run 为 0），run_metrics 终态行 MUST 透传该键，两条透传链（`_metrics_latency` 公共 helper 与成功路径）同覆盖、不漏。三常量（统计线 60s / 期内告警线 120s / 分级线 300s）同值不同义、禁止合并的既有约束保持并加注释。

#### Scenario: 总秒键求和与透传
- **WHEN** 某 run 的延迟样本含多个超统计线样本并经任一终态路径收尾
- **THEN** latency_stats 输出 latency_stall_total_seconds 等于超线样本求和，run_metrics 终态行携带同值键

#### Scenario: 无停滞 run 供数
- **WHEN** run 无延迟样本或全部样本不超统计线
- **THEN** latency_stall_total_seconds 为 0，run_metrics 行照常携带该键

### Requirement: 车道级日汇总

self_review 停滞聚合 MUST 在既有扫描同一遍内按 agent_type 分组输出车道级日汇总行（停滞总秒 / run 数 / 最大单次 / 是否超阈值标注），不新增 IO、不新建扫描器；摘要仍遵守自省只读铁律（不产生 admin 告警、不写任何文件）。

#### Scenario: 车道分组汇总行
- **WHEN** 窗口内多个车道均有停滞 run
- **THEN** 摘要按 agent_type 各出一行车道级日汇总（总秒 / run 数 / 最大单次），附阈值标注

### Requirement: 车道日累计阈值告警

admin_monitor MUST 在 api-stall 收尾检测循环内维护车道×日累计计数器（读终态 run_metrics 行按 lane+date 求和），累计超阈值发 info 级 signal 提示 provider 拥塞；阈值配置化（`admin.lane_stall_warn_minutes`，缺省各车道统一 30 分钟，0=关闭）。信号文案含累计秒数。去重键=lane+date：同车道同日至多一条——去重 MUST 经 merge_signal 持久键跨重启生效：信号携带稳定 `_fp`（=lane+date）进 status_hash 的 daemon 级指纹位，指纹不含累计秒数（文案数值变化不拆记录）；同日重复超阈值仅刷 last_seen 不新增记录，跨日（date 变化）指纹自然过期，daemon 重启后无需重建去重状态。

#### Scenario: 超阈值发信与同日去重
- **WHEN** 某车道当日停滞总秒累计超阈值，且同日该车道再次超阈值
- **THEN** 首次超阈值发一条 info 级信号；同日重复超阈值不新增记录、仅刷 last_seen（每车道每日至多一条）

#### Scenario: 阈值配置语义
- **WHEN** admin.lane_stall_warn_minutes 取缺省或配置为 0
- **THEN** 缺省为各车道统一 30 分钟；0=关闭告警

#### Scenario: 重启后计数重建不重复发信
- **WHEN** daemon 重启，当日已有超阈值停滞且已发过同 lane+date 信号
- **THEN** 当日计数从已落账 run_metrics 行重建，同日不再发第二条 lane+date 记录

### Requirement: 既有单 run 观测行为不变

既有单 run 分级（classify_round_stall）与升级信号（api_round_stall_escalated，success 终态豁免）行为 MUST 不变；缺新键的存量 run_metrics 行按 0 计，不回填历史。

#### Scenario: 升级信号行为不回归
- **WHEN** 某非 success 终态 run 的 latency_max 超分级线，另一 success 终态 run 停滞超线
- **THEN** 前者照常发 api_round_stall_escalated，后者维持 success 豁免不发信号

#### Scenario: 存量行兼容
- **WHEN** 读取无 latency_stall_total_seconds 键的存量终态 run_metrics 行
- **THEN** 按 0 计入车道日累计，不回填历史行
