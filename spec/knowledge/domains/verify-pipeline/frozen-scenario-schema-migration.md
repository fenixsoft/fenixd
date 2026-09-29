# 冻结场景结构迁移
<!-- knowledge: capability=frozen-scenario-schema-migration rev=1 sources=spec/archive/2026-09-19-evo-add-frozen-scenario-schema-migration -->

冻结场景文件的旧 schema 兼容迁移：字段重命名演进后旧冻结集自动迁移通过验收，不以笼统 corrupt 判死、不逼人工裁决。

## 现行规则

- 读侧旧 schema 迁移：加载冻结场景文件时识别旧字段形态——run 步骤的 `value` 迁移为 `command`，output_match 断言的 `value` 迁移为 `expected`；迁移后走既有校验。
- 迁移仅对「目标字段缺失且旧字段存在」生效；新 schema 字段已存在时零干扰、不做迁移。
- 迁移失败的条目报错列出具体字段差异（场景 id / 下标 / 缺失字段清单），不以笼统 `corrupt` 吞掉诊断信息。
- schema 版本标记：场景写入端在持久化文件中恒定写入 `schema_version` 结构化标记；读侧按版本路由——当前版本直通、旧版本迁移、未知版本保守按迁移尝试 + 差异报错。
- blocked_stuck 处置后自动复位：admin 处置成功（disposition `result=resolved`）且修好根因、spec 仍处 blocked 且阻塞类型为 blocked_stuck 时，自动复位 spec 状态（复用 env 阻塞族复位范式：实现分支已合并则直通重验，否则回 ready），不等人工二次介入；处置 run 无 `result=resolved` 时不动状态。

## 溯源

- [2026-09-19 evo-add-frozen-scenario-schema-migration](spec/archive/2026-09-19-evo-add-frozen-scenario-schema-migration/) — 新增读侧旧字段迁移、`schema_version` 版本标记与字段级差异报错，并把 blocked_stuck 纳入处置成功后自动复位集合
