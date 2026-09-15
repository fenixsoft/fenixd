# verdict-failure-passthrough — 裁决失败信息的结构化透传

## ADDED Requirements

### Requirement: 告警携带 violations 明细
`cause=violations` 触发的 `verdict_evidence_invalid` 告警 SHALL 在 evidence 中携带结构化 violations 明细（逐条 `scenario_id` + `reason`，超过 20 条截断并注明总数）；MUST NOT 仅输出固定概要文案。

#### Scenario: 告警可读出每条违规
- **WHEN** 二次校验仍违规触发 `verdict_evidence_invalid`
- **THEN** 告警 evidence 含违规场景清单及各自原因，人工无需读 report.json 即可定位违规形状

### Requirement: STATE error 按 cause 生成
裁决证据校验失败落盘的 STATE error SHALL 按 cause 生成：「重试一次仍不合规」表述 MUST 仅出现在 `cause=violations`（重试确实发生）路径；frozen/cancelled/异常/派发失败路径 MUST NOT 产出引用「已重试」的文案（让位路径按 verdict-failure-semantics 零写入，不落 error）。

#### Scenario: 文案与事实一致
- **WHEN** 重试派发被拦截（任何 cause 非 violations 的失败）
- **THEN** STATE 中不存在「重试一次仍不合规」或等义表述

### Requirement: 失败历史侧车
pm_engine SHALL 维护 `.fenix/verify-progress/<spec>/fail_history.json`：每轮裁决采纳失败时原子追加 `{round, cause_type, failed_scenarios}` 条目；spec 进入终态（verified/pushed）时清空。侧车写盘失败 SHALL 静默降级（分型标注 unknown），不阻断升级闸门。

#### Scenario: 连续失败轮留痕
- **WHEN** 同一 spec 连续 2 轮裁决失败（第 1 轮 bug-found、第 2 轮证据不合规）
- **THEN** fail_history.json 含两条记录，cause_type 分别为 real-bugs 与 evidence-invalid，failed_scenarios 为各自轮次的失败场景集合

#### Scenario: 终态清空
- **WHEN** spec 验证通过进入终态
- **THEN** fail_history.json 被清空（或删除），不留陈旧失败记录

### Requirement: 升级告警携带失败分型与轮间 diff
`verify_fail_escalation` 告警 SHALL 在 evidence 中携带：① 失败分型——各失败轮归类为 `evidence-invalid`（证据校验不合规）/ `real-bugs`（真缺陷）/ `repeat`（失败场景集与上轮完全相同）/ `unknown`（侧车缺失）；② 相邻两轮 failed_scenarios 的 diff（新增/消失/持留）。`fail_rounds` 计数逻辑本身 MUST 保持不变（本需求仅增强透传）。

#### Scenario: 同失败集连续出现可识破
- **WHEN** 升级闸门因连续失败轮触发冻结，且侧车显示各轮失败场景集完全相同
- **THEN** 告警 evidence 分型含 `repeat` 并给出「相邻轮 diff 为空」的事实陈述，人工可据此判断是否存在「根因已修复但闸门仍冻结」的误置情形（对照 2026-09-08T19:12 误置冻结）

#### Scenario: 真缺陷失败的分型可见
- **WHEN** 连续失败轮中存在 bug-found 轮且失败场景集逐轮缩小
- **THEN** 告警 evidence 的 diff 显示持留/消失场景分布，呈现修复进展

### Requirement: 轮次口径命名区分
涉及验证失败轮次的日志与告警文案 SHALL 显式区分两套计数器的名称：「原地打回第 N 轮」（bug-found 打回链计数）与「升级闸门连续失败第 N 轮」（fail_rounds 计数），MUST NOT 使用不带限定的「第 N 轮 / 连续失败 N 轮」裸表述致使两套口径混淆。

#### Scenario: 文案无口径歧义
- **WHEN** 审读同一 spec 同日的打回日志与升级告警
- **THEN** 两处文案各自带口径限定词，读者无需推断即可区分
