# 冻结场景 dict 包裹机械拯救

<!-- knowledge: capability=frozen-scenario-salvage rev=1 sources=spec/archive/2026-11-02-fix-frozen-scenario-dict-salvage -->

冻结场景装载读端对 `test_scenarios.json` 顶层 dict 包裹形态先机械解包止损再装载：可拯救的解包继续装载流程，不可拯救才转人工，dict 包裹不再引发场景计划争议冻结轮。

## 规则

- 接线位置：冻结装载读端读入 `test_scenarios.json` 后，在顶层「期望 JSON 数组」检查内部处理——顶层非数组时先判「dict 且含 `scenarios` 数组键」，再落既有 corrupt 分支。
- 可拯救路径：走既有机械拯救单源实现（`_salvage_top_level_dict`，内部即 `salvage_scenarios_file`）——解包 → 重过既有全部场景校验 → 以解包后的纯数组原子重写落地（非仅内存采纳）；不写第二份解包实现。
- 解包成功即装载：拯救返回的列表直接作为顶层内容继续既有冻结契约迁移（`frozen_contract_version`）与装载流程；文件已被拯救原子重写为纯数组，内存与磁盘一致。拯救成功不触发场景计划争议。
- 解包留痕：解包前落 WARNING（顶层键、条目数）；成功/不适用日志由拯救助手既有 WARNING/INFO 承担，冻结读端不新增日志形态。
- 不可拯救路径：顶层 dict 无 `scenarios` 数组键、解包后条目仍不通过既有场景校验、原子重写失败（含异常兜底）——一律落回既有 corrupt → env_blocked 人工通道（场景计划争议转人工），保留原错误文案与处置选项，行为与无拯救时逐位一致。
- 纯数组零干扰：顶层已是合法 JSON 数组时行为不变——不触发拯救、不额外重写或备份，既有契约迁移路径不受影响。
- 接入判据（时序暴露面）：冻结装载读端先于验收归因点消费场景产物，时序上无法依赖拯救先行落地，必须自带拯救接线；读取时序在拯救落地之后的读端（fastlane、verdict_evidence 等）不接助手，恒可假设顶层为纯数组。

## 溯源

- 2026-11-02 fix-frozen-scenario-dict-salvage（spec/archive/2026-11-02-fix-frozen-scenario-dict-salvage/） — 新增冻结装载读端 dict 包裹机械拯救接线（可拯救解包重写装载、不可拯救落回 corrupt→env_blocked 人工通道、纯数组行为不变）
