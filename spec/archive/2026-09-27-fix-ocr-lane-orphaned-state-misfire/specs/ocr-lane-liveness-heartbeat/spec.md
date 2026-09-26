## ADDED Requirements

### Requirement: ocr 车道运行中心跳事件
ocr 审查车道（`run_impl_ocr`）在审查子进程运行期间，框架侧 SHALL 以不超过 60 秒的间隔向该车道 run 转录（`.fenix/runs/impl-ocr-<spec>-<ts>.jsonl`）追加 `progress` 心跳事件；子进程返回或触发车道硬超时后 MUST 停止心跳。心跳事件 MUST 携带 `spec`、`agent_type: "impl-ocr"`、`timestamp` 与审查进度摘要（review 区间 from/to、已用时秒数）。心跳 MUST NOT 改变「终态事件末行后置」不变量：`result`/`error` 终态事件 MUST 是文件最后一行（停跳先于终态写入）。

#### Scenario: 大 diff 审查期间持续心跳
- **WHEN** ocr 车道正在审查大 diff（子进程运行中超过 120 秒）
- **THEN** 车道 run 转录在运行期间以 ≤60s 间隔持续追加 `progress` 事件，文件 mtime 持续刷新，每个 `progress` 事件含 review 区间与已用时

#### Scenario: 子进程收尾后停跳且终态末行后置
- **WHEN** 审查子进程返回（完成/非零退出/硬超时）
- **THEN** 心跳停止，不再有新 `progress` 事件追加；随后写入的终态事件（`result` 或 `error`）是文件最后一行

### Requirement: 心跳与无驱动探针的相容语义
orphaned_state 无驱动判定（`spec_is_undriven`，admin_monitor 与 event_bus 恢复共用）MUST 保持现状**零改动**；其条件①（run 文件 mtime 宽限窗）因心跳事件持续刷新而自然为假——车道在跑期间 spec 不被判「无驱动」，orphaned_state 不成条。框架 MUST NOT 为 STATE 的 `_ocr_join_wait` 增加任何有意等待豁免：daemon 重启后心跳停止，宽限+阈值过后 spec 回归既有 orphaned_state 上报与处置直通道自愈链。

#### Scenario: 车道在跑不再误报孤儿
- **WHEN** spec 处于 testing 且 ocr 车道在跑、心跳事件持续刷新 run 转录 mtime、状态停留超过 orphaned_state 阈值（15 分钟）
- **THEN** `spec_is_undriven` 返回 False，orphaned_state 信号不成条，Administrator 不被唤起

#### Scenario: 重启停跳后真孤儿仍上报
- **WHEN** daemon 在车道运行中重启（心跳线程随进程消失，run 转录 mtime 停滞），spec 状态停留超过 orphaned_state 阈值且无其他驱动
- **THEN** `spec_is_undriven` 返回 True，orphaned_state 正常成条——既有「admin 处置 → testing→verifier 重验入队」自愈链不被遮蔽

### Requirement: 心跳事件对终态分类器透明
`progress` MUST NOT 被 dashboard `classify_run`（`core/dashboard/data/runs.py`）与 `AdminMonitor._run_terminal_status` 判为任何终态：二者对未知/非终态事件类型的缺省 `running` 兜底即满足本要求，并以回归测试钉住。运行记录与时间轴渲染层 MUST 容忍 `progress` 事件（不识别则忽略，不报错、不误判终态）。

#### Scenario: 心跳末行时 run 判 running
- **WHEN** 车道 run 转录当前末行是 `progress` 心跳事件
- **THEN** `classify_run` 与 `_run_terminal_status` 均返回 `running`（非 done/error/其他终态），时间轴 run 节点显示运行中

#### Scenario: 渲染层容忍心跳事件
- **WHEN** 运行记录/时间轴读取含 `progress` 事件的车道 run 转录
- **THEN** 渲染不报错不崩，未知事件按既有降级路径处理（忽略或按运行中呈现）
