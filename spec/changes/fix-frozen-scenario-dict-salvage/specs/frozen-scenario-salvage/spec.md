## ADDED Requirements

### Requirement: 冻结场景文件顶层 dict 包裹机械拯救

冻结场景装载读端读入 `test_scenarios.json` 后、执行顶层「期望 JSON 数组」检查前，若顶层为 dict 且含 `scenarios` 数组键，MUST 先走既有机械拯救（解包 → 重过既有全部场景校验 → 以解包后的纯数组原子重写落地），解包成功则以解包结果继续既有冻结契约迁移与装载流程，MUST NOT 触发场景计划争议。解包前 MUST 落 WARNING 留痕（顶层键、条目数）。解包不可拯救（顶层 dict 无 `scenarios` 数组键、解包后条目仍非法、原子重写失败）时 MUST 落回既有 corrupt → env_blocked 人工通道，行为与接线前逐位一致。顶层已是纯数组时 MUST 行为不变（不触发拯救、不额外重写）。

#### Scenario: dict 包裹且场景条目合法
- **WHEN** 冻结场景文件顶层为 `{"spec": "...", "total": N, "scenarios": [...]}` 且 scenarios 数组内条目全部通过既有场景校验
- **THEN** 读端解包并以纯数组原子重写该文件，按解包结果继续契约迁移与装载，冻结轮正常推进，不产生场景计划争议，日志含解包 WARNING 留痕

#### Scenario: dict 包裹但解包后条目仍非法
- **WHEN** 冻结场景文件顶层为 dict 且含 scenarios 数组，但数组内存在不通过既有场景校验的条目
- **THEN** 拯救返回不可拯救，读端按既有 corrupt → env_blocked 通道处置（场景计划争议转人工），与接线前行为一致

#### Scenario: 顶层 dict 但无 scenarios 数组键
- **WHEN** 冻结场景文件顶层为 dict 且不含 `scenarios` 数组键
- **THEN** 拯救判定不可拯救，按既有 corrupt → env_blocked 通道处置

#### Scenario: 顶层纯数组行为不变
- **WHEN** 冻结场景文件顶层为合法 JSON 数组
- **THEN** 装载流程与接线前逐位一致：不触发拯救、不产生额外重写或备份，既有契约迁移路径不受影响
