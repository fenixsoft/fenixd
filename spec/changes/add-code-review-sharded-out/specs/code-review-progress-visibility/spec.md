# code-review-progress-visibility 规格（聚合进度与停滞告警）

## ADDED Requirements

### Requirement: 进度读侧聚合分片

code-review 运行进度的读取（`read_progress`）SHALL 聚合「主产物 + 全部分片」计算进度：`done` MUST 为主产物与全部 `out-<run_id>-b<N>.jsonl` 分片有效行数之和；`current` MUST 取最后落盘来源（按文件 mtime 最晚者末行）的文件名；`total` 口径不变（manifest 长度）。响应字段形状 MUST NOT 变化（`running`/`review_id`/`review_kind`/`total`/`done`/`current`）。

- 分片发现 MUST 基于目录 glob `out-<run_id>-b*.jsonl`，主产物缺失时进度 MUST NOT 归零（只要有分片行）。
- 无效行（空行、不可解析行）MUST NOT 计入 `done`，且 MUST NOT 使读取失败。

#### Scenario: 分片进度实时可见

- **WHEN** run `running`，主产物不存在，分片 `b1` 有 17 行、`b2` 有 9 行有效行
- **THEN** `read_progress` MUST 返回 `done=26`、`total=manifest 长度`、`running=true`

#### Scenario: 主产物缺失不归零

- **WHEN** 主产物被清理或从未创建，但分片合计 26 行
- **THEN** `read_progress` MUST 返回 `done=26`，MUST NOT 回退为 0

### Requirement: 事中零进度停滞告警

code-review run 处于 `running` 且聚合 `done==0` 持续超过可配置阈值（缺省 15 分钟）时，框架 SHALL 产生一条 admin 人工告警（kind 归入 code-review 车道），提示「审查零进度已持续 X 分钟，疑似子代理等待收工模式」。同一 run 的停滞告警 SHALL 去重（单 run 至多一条），run 到达终态后 MUST NOT 再触发。

- 阈值 MUST 经 `admin.code_review.stall_alert_minutes` 配置（缺省 15，非法值回退缺省）；设置页（settings 分面 admin 作用域）MUST 同步提供该键的配置界面（「新增配置项必须带 Dashboard 界面」约定）。
- 告警文案 MUST 包含 run_id、已运行时长、聚合 done 值，供人工直接判断是否取消。

#### Scenario: 零进度超阈值触发告警

- **WHEN** run `running` 已 16 分钟，主产物与分片合计仍 0 行
- **THEN** 框架 MUST 发出一条含 run_id 与已运行时长的 admin 告警，且同一 run 不重复发送

#### Scenario: 正常推进不告警

- **WHEN** run `running` 已 16 分钟，聚合 done 为 30 且持续增长
- **THEN** 框架 MUST NOT 发停滞告警

#### Scenario: 阈值非法回退缺省

- **WHEN** `admin.code_review.stall_alert_minutes` 配置为 `-5` 或非整数
- **THEN** 阈值 MUST 回退 15 分钟，行为与缺省一致
