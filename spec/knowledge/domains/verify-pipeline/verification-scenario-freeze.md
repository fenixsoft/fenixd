# 场景冻结契约版本化
<!-- knowledge: capability=verification-scenario-freeze rev=1 sources=spec/archive/2026-09-24-evo-frozen-scenario-contract-versioning -->

冻结场景集的验收契约版本化管理：契约规则升级后旧冻结集自动迁移或自动重出题，不再整轮报废等人工裁决。

## 现行规则

- 契约版本字段：冻结场景条目支持 `contract_version` 整型字段，标识该条目符合的场景验收契约规则版本；缺失或非整型视为 1（存量兼容）。系统加载冻结集时读取该字段并路由迁移逻辑；写盘路径（`prepare_scenarios_for_write`）恒定写入当前版本，新产出冻结集天然为当前契约版本。
- 读端验收前迁移：`contract_version` 低于当前版本且可机械迁移时（如 v1 的 web 场景缺 navigate 步骤且引擎可供给被测实例 `base_url`），在读端验收（`load_scenarios`）之前完成迁移——以 `base_url` 合成 navigate 步骤（URL 写入步骤 `value` 字段，与全链路读取口径一致）插入 steps 首位，条目版本升至当前并写回冻结文件；无法获得 URL 的 web 场景移入 `pending_replan` 列表并从本轮集合剔除（剩余场景继续冻结执行）。
- 版本已匹配直通：`contract_version` 等于当前版本时不迁移、不写回、不备份，直接进入场景验收。
- 全场景过时自动重出题：迁移后无任何合法场景（`aborted='all_scenarios_stale'`，含冻结集为空）时，删除 test_scenarios.json 使本轮回落到既有出题分支（下轮生成当前契约版本的场景集），不置 blocked/env_blocked 待人工、不递归调用验证流水线。
- 非契约类损坏维持人工通道：JSON 语法错误、非契约类规则不匹配、无迁移路径（`aborted='no_migration_path'`）等加载失败维持既有 corrupt → env_blocked 人工裁决通道；本机制的自动迁移/重出题只覆盖契约类漂移。
- 迁移日志与审计：每次契约迁移写 INFO 日志（场景总数、成功迁移数、移除过时数、版本变更）；被移除的 `pending_replan` 场景写 WARNING 并附 id 列表；迁移无法完成（未登记版本段/写回失败/迁移后仍验收失败）留痕 ERROR/WARNING 并交既有异常通道，不静默吞掉。
- 多版本迁移链：以版本号登记表 + 逐段推进循环支持从任意旧版本直接迁移到当前版本（跳版本迁移），每个版本的迁移逻辑为独立函数；未登记版本段或无可用迁移路径时 fail-closed，不猜测、不跳过版本。

## 溯源

- 2026-09-24 evo-frozen-scenario-contract-versioning（spec/archive/2026-09-24-evo-frozen-scenario-contract-versioning） — 新增条目级 `contract_version` 字段、读端验收前自动迁移、全场景过时自动重出题与多版本迁移链（此前验收契约每次演化都会把旧冻结集判 corrupt、整轮验证报废并转人工裁决）
