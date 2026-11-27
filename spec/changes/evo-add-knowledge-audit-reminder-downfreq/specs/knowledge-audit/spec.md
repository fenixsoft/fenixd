# 能力：知识真相源体检（knowledge-audit）

## 目的

对 spec/knowledge 知识页做周期体检（规则冲突、过期项、语义项转写失败），病灶分级登记 .fenix/knowledge_audit_findings.json；escalated 级疑点聚合提醒进 todo.md 等待人工仲裁——人工在 .fenix/knowledge_audit_arbitration.json 按 fingerprint/decision/decided_at/note 登记，检查点自动消费后提醒停止。

## 提醒面节拍（本能力修订）

- 首拍与条目集变化：escalated 指纹集相对上次提醒发生变化（含首次出现、以及减少）→ 当日体检收尾照常 upsert 聚合行并提交，行尾附「（下次重复提醒不早于 YYYY-MM-DD）」（本地日 +7 天）。
- 重复提醒降频：条目集未变且距上次提醒 <7 天 → 跳过 upsert（无写盘无提交，log.info 留痕）；≥7 天 → 恢复一拍并刷新状态键与下次提醒尾注。
- 清理旁路：escalated 清零时忽略降频，照常执行纯清理语义摘除 todo 残留行，并重置状态键。
- 状态键：knowledge_audit_state.json 记 last_escalated_reminder_date（上次实际拍出日）与 last_escalated_set（排序指纹列表），写入持既有 _state_write_lock 并回读合并（同 last_audit_date 口径）。

## 仲裁消费（不变）

consume_arbitration 挂 300s 检查点、自然日防重短路之前，人工登记当日生效；decision 合法值 fixed / no-conflict / false-positive；清单文件接受裸数组或 decisions 包裹双形态。