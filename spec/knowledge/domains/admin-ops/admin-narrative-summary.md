<!-- knowledge: capability=admin-narrative-summary rev=1 sources=spec/archive/2026-09-02-add-admin-activity-view -->

# 处置叙述性总结

Administrator 每次处置产出人类可读的叙述总结，随处置记录落盘供运维界面展示。

## 现行规则

- Administrator 处置完成后向处置实例文件写入 `summary` 字段：一段人类可读的叙述性总结，包含诊断结论（问题是什么、根因）、处置时间线（做了什么、顺序）、最终结果、以及对人类决策的建议。
- `summary` 随处置记录落盘到 `.fenix/admin_alerts.json` 的 disposition 记录中，供 Dashboard 展示。
- 无法自主处置（escalate=true）时，`summary` 明确说明为何需人工介入，并给出具体建议动作。
- 处置记录按 `admin_run_id` 归并到运维记录时间线，消除「永久处置中」假象。
- 存量记录无 `summary` 字段时，界面降级显示结构化字段（actions_taken/result），不报错。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：admin 处置产出叙述总结并按 admin_run_id 归并运维记录时间线
- 2026-09-02 add-admin-activity-view（spec/archive/2026-09-02-add-admin-activity-view） — 固化 summary 字段契约：诊断结论/处置时间线/结果/人工建议四要素、escalate 场景的明确建议与旧记录降级兼容
