## ADDED Requirements

### Requirement: 声明现实处方覆盖 delete 条目

派发前「声明清单 × 仓库现实」快照与处方段 MUST 覆盖 `kind: delete` 条目，按其特有语义给出两种形态：

- 路径在主树**存在** → 标注为删除目标确认（该文件应在本次实现中被移除）；
- 路径在主树**不存在** → 无可删，标注疑似声明笔误，并附 basename 模糊匹配候选（与 `new` 的既有候选机制同源）。

快照对 `delete` 条目 MUST 保留 `kind` 字段（与既有条目结构一致），使实现 agent 无需回读声明段即可判断该路径的期望方向。

#### Scenario: delete 目标存在的处方

- **WHEN** 声明段含 `- path: __init__.py` + `kind: delete`，主树存在该文件
- **THEN** 处方段列出该路径并标注为删除目标确认

#### Scenario: delete 目标不存在时给候选

- **WHEN** 声明段含 `- path: core/legacy_typo.py` + `kind: delete`，主树无该文件但仓库内存在 basename 唯一命中 `core/legacy.py`
- **THEN** 处方段标注该路径主树不存在、疑似声明笔误，并列出候选 `core/legacy.py`

### Requirement: delete 条目的裁决归宿收窄

LLM 终审对 `kind: delete` 条目 MUST 拒绝 `reference` 归宿：`reference` 的语义是「转为仅审计、不再硬校验」，施加于 `delete` 即让删除要求静默消失，与守卫的防洗白设计冲突。judge 对该类条目给出 `reference` 时，机械执行层 MUST 改写为 `unclear` 转人工裁决，并留审计痕迹。

`delete` 条目的可用归宿为 `typo` / `missing` / `unclear`：

- `typo` → 修正声明路径后重跑守卫（既有机械执行路径）；
- `missing` → 既有打回/重派路径；
- `unclear` → 既有 dispute 转人工话术。

#### Scenario: delete 条目的 reference 裁决被改写为 unclear

- **WHEN** judge 对一条 `kind: delete` 的违规条目输出 `verdict: "reference"`
- **THEN** 机械执行层 MUST NOT软化该条目
- **AND** 该条目按 `unclear` 处理，走既有 dispute 转人工通道
- **AND** 审计记录保留 judge 的原始 verdict 与改写事实

#### Scenario: delete 条目的 typo 裁决正常执行

- **WHEN** judge 对一条 `kind: delete` 的违规条目输出 `verdict: "typo"` 与 `actual_path`
- **THEN** 按既有机械执行路径修正声明段路径并重跑守卫

#### Scenario: delete 条目的 missing 裁决走重派

- **WHEN** judge 对一条 `kind: delete` 的违规条目输出 `verdict: "missing"`
- **THEN** 走既有打回/重派路径，重派提示词含结构化的 `undeleted` 违规条目

### Requirement: 违规条目话术按 kind 分化

守卫违规清单以结构化条目（`path` / `kind` / `violation`）贯穿至 dispute 匹配、LLM 终审输入与重派话术三处消费点：`violation: undeleted` 的条目 MUST 表述为「未删除该路径」语义，`violation: missing` 维持既有的「缺件」语义。MUST NOT 对 `delete` 条目使用「缺件」表述——文件明明存在，该表述会同时误导人工阅读与 judge 的归因判断。

#### Scenario: 重派话术区分未删除与缺件

- **WHEN** 守卫返回一条 `undeleted` 与一条 `missing`，进入重派路径
- **THEN** error 文案对前者使用「未删除」语义、对后者使用「缺件」语义，两者均含路径

#### Scenario: dispute 匹配按路径生效不因 kind 失效

- **WHEN** 实现 run 对一条 `kind: delete` 的违规条目在 `.fenix-run-result.json` 中登记 `deliverable-dispute`
- **THEN** 该异议被识别并走既有 blocked 人工裁决路径，不自动重派
