## ADDED Requirements

### Requirement: implemented 停留态的恢复出口

fast-track spec 停留 `implemented` 且恢复形态三条件同时成立——①`status == "implemented"` 且 `implementer_run` 非空；②实现者 run 流转录文件 mtime 超过孤儿宽限窗（`ORPHANED_RUN_GRACE_SECONDS` 同语义）；③dispatcher 无本 spec 在飞 OCR 车道——时，事件恢复循环重发的 `spec_implemented` MUST NOT 被 fast-track 短路静默丢弃，MUST 重入收尾推进（implemented → testing → OCR join 门禁 → verified → done）。三条件任一不成立时 MUST 维持既有短路行为（孤儿 planner 防线不变），并保持 debug 级留痕。

#### Scenario: 死态恢复重入走完收尾

- **WHEN** fast-track spec 停留 implemented、实现分支已 merge 回主树、实现者 run 已死（转录 mtime 过宽限窗）、无在飞车道，恢复循环重发 spec_implemented
- **THEN** 重入收尾：状态推进 implemented → testing，OCR join 门禁裁决（产物缺失则幂等补启车道并 defer 停等），车道完成回调唤醒后续 verified → done 推进

#### Scenario: 停等期回调闭环

- **WHEN** 恢复重入后 join 门禁 defer，spec 停留 testing 等待补启车道
- **THEN** 车道完成回调 `_on_impl_ocr_lane_finished` 按既有唤醒路径重评 join（status==testing 满足回调前置），pass 则推进 verified，全程无需再次重启或人工介入

#### Scenario: 正常收尾流不触发重入

- **WHEN** fast-track run 正常收尾连跳（implemented → testing 同一 run 上下文毫秒级完成），恢复循环其后重发 spec_implemented
- **THEN** 因 status 已非 implemented（或转录 mtime 新鲜、车道在飞三条件不成立），维持既有短路，不派孤儿 planner run、不重复推进

#### Scenario: 恢复重入不读结果文件

- **WHEN** 恢复重入执行收尾推进（结果文件已在首次收尾时消费清理）
- **THEN** 重入路径不读 fast-track 共享结果文件，verified→done 门禁以 per-spec impl-result 快照（merge 成功时点已落盘）与任务勾选为准

#### Scenario: 重入动作可观测

- **WHEN** 恢复形态三条件成立触发重入
- **THEN** 记录 INFO 级日志（spec 名、判据结果、执行动作），不再静默丢弃
