# 验证报告：evo-frozen-scenario-contract-versioning

> ⚠️ 本报告由框架于 2026-09-19T00:40:11Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-19T00:40:11.275289+00:00

## 结论：✅ 通过（verified）

**状态：verified — 16/16 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 16/16 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 16 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.17M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| contract-v1-web-navigate-autofill | R1 首次契约升级自动迁移（纯函数级）：v1 web 场景缺 navigate + 引擎供给 base_url → 迁移合成 navigate 步骤（URL 写入 value 字段）插入 steps 首位、条目 contract_version 升至 2，迁移结果过 validate_scenario_dicts 验收；迁移为纯函数不改输入列表（spec.md R1 契约版本字段 / design D2.2） | pass | 0/3 | - |
| contract-url-candidate-priority | 迁移 URL 候选取值顺序：场景内 step 顶层 url 字段（http/https）优先于 base_url；非 http(s) url 字段（相对路径）不作为候选、回退 base_url（design D2.2 顺序 a / spec.md R1 首次契约升级自动迁移） | pass | 0/3 | - |
| contract-run-url-not-mined | MUST NOT 从 steps 文本挖 URL：web 场景 steps 含 run 步骤且命令内含 URL 但无 navigate → 不挖文本，改用 base_url 合成 navigate（design D2.2 约束 / spec.md R1） | pass | 0/2 | - |
| contract-partial-migration-replan | 部分迁移成功：base_url 为空且场景无 url 字段 → 该场景移入 pending_replan 并从本轮剔除，其余 cli 场景照常迁移并盖 contract_version=2 戳（spec.md R2 Scenario 部分迁移成功） | pass | 0/2 | - |
| contract-all-stale-replan | 全部过时语义（纯函数级）：全量 pending_replan 或空集合 → aborted='all_scenarios_stale'、migrated 为空（spec.md R2 Scenario 全部过时自动重新出题） | pass | 0/3 | - |
| contract-existing-navigate-stamp-only | 迁移分支最小改动：已有 navigate 的 web 场景 / cli / api 场景 → 只盖 contract_version=2 戳、步骤零变化（design D2.2 分支 1/2 / spec.md R1） | pass | 0/2 | - |
| contract-idempotent-v2-zero-op | 幂等与版本路由：contract_version=2 集合 → 迁移零操作（返回原集合）；缺失/非整型 contract_version 视为 1、集内取 min 路由（spec.md R1 Scenario contract_version 已匹配 / design D1） | pass | 0/3 | - |
| contract-jump-version-chain | 多版本迁移链：跳版本 v1→v3 经登记表两段迁移推进（前段产物喂后段）；未登记版本段 → aborted='no_migration_path'（fail-closed，spec.md R4） | pass | 0/3 | - |
| contract-write-end-stamp | 写端回归：prepare_scenarios_for_write 恒定盖 contract_version=当前版本戳（新产出冻结集天然当前契约版本、下轮加载零迁移）；盖戳不改既有 navigate 步骤（spec.md R1 写盘路径 / design D1） | pass | 0/3 | - |
| contract-pipeline-migrate-writeback-backup | pipeline 调用点首次迁移：v1 冻结文件 → 迁移先于验收执行、写回后 contract_version=2 与 schema_version 持久化、.contract-v1.bak 备份存在且为迁移前原样、迁移结果回注 _frozen_migrated、未升级人工（spec.md R1 Scenario 首次契约升级自动迁移 / design D4） | pass | 0/2 | - |
| contract-pipeline-all-stale-delete-replan | pipeline 调用点全场景过时：全部场景无法定位 URL 或冻结集为空 → 删除 test_scenarios.json、返回 (None, False) 回落既有出题分支、未调用 _escalate_env_blocked（spec.md R2 Scenario 全部过时自动重新出题 / design D3） | pass | 0/3 | - |
| contract-pipeline-idempotent-zero-op | pipeline 幂等零操作：contract_version=2 冻结集 → 不调 base_url、不写回、不备份，直接进入场景验收（spec.md R1 Scenario contract_version 已匹配 / design D4 幂等） | pass | 0/2 | - |
| contract-pipeline-acceptance-fail-option3 | 迁移后验收仍失败 → 维持 corrupt → env_blocked 且处置选项含第③条回退指引（删除/恢复 .contract-v1.bak）；未被迁移（v2）验收失败则完全维持现状、无第③条（spec.md R2 其他加载失败维持人工 / design D4 风险处置） | pass | 0/3 | - |
| contract-pipeline-corrupt-json-escalates | 非契约类漂移维持人工通道：JSON 语法错误 → corrupt → env_blocked（不迁移、不备份、不删除文件）；无冻结文件 → (None, False) 走既有出题通道（spec.md R2 除全过时外的加载失败维持 corrupt → env_blocked） | pass | 0/3 | - |
| contract-migration-audit-info-log | 迁移日志与审计（R3）：迁移成功 MUST 写 INFO 日志含场景总数、成功迁移数、移除过时数、contract_version 变更（1→2）（spec.md R3 迁移日志与审计） | pass | 0/2 | - |
| contract-migration-partial-warn-log | 迁移日志与审计（R3）：被移除的 pending_replan 场景 MUST 写 WARNING 并附场景 id 列表（spec.md R3 迁移日志与审计） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 16 个（第 1 轮）。

- 首轮写入 16 个场景

