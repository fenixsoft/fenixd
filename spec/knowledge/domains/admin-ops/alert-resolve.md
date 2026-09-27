<!-- knowledge: capability=alert-resolve rev=1 sources=spec/archive/2026-09-27-add-human-adjudication-choices -->

# 告警一键裁决处置端点

`POST /api/alert-resolve`：一次选择完成「动作执行 + 状态推进 + handled + 留痕」的处置闭环。

## 现行规则

- 端点 `POST /api/alert-resolve`（`core/dashboard/routes/alert_routes.py`）接受 `{project, alert_id, choice_id, note?}`，按序完成且对外表现为一次调用：(1) 校验告警存在且未 handled，按告警 `signal_type` 从注册表校验 `choice_id` 合法；(2) 执行 choice 映射的后端动作（复用 admin_actions 既有动词或裁决动词）；(3) 将 spec 状态机推进到该裁决的目标终态（含冻结解除、计数器处置、error 清理）；(4) 标记告警 handled 并落处置留痕。
- kind 差异：`kind=ESCALATION` 告警走既有 `AdminStore.mark_handled`（该方法仅匹配 ESCALATION）；`kind=SIGNAL` 记录（如 `build_artifact_paths_missing`）由端点直接更新其 handled 字段。
- 非法选择（choice_id 不在该信号的选项集）返回 400 级错误并说明合法选项集，spec 状态与告警 handled 状态均不变；对已 handled 告警重复提交返回冲突错误，不重复执行动作。
- 任一步失败返回结构化错误且不标记 handled；已执行的前序动作在错误信息中如实报告，不做虚假回滚声明，spec 保持可重试裁决。
- 成功处置在 `admin_alerts.json` 落一条 `kind=disposition` 记录：含 signal_type、spec、choice_id、note（人工备注，可空）与执行动作摘要；该记录对 dashboard admin 活动区可见，作为裁决审计轨迹。
- 人工下拉处置产生的留痕不依赖手写四段散文模板，满足「清除告警 ≠ 处置留痕」的治理要求。

## 溯源

- 2026-09-27 add-human-adjudication-choices — 建立 alert-resolve 端点：选择即完整闭环、ESCALATION/SIGNAL 双 handled 通道、失败不虚假标记与结构化 disposition 留痕
