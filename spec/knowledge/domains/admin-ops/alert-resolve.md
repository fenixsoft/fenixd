# 告警一键裁决处置端点

<!-- knowledge: capability=alert-resolve rev=2
     sources=spec/archive/2026-09-27-add-human-adjudication-choices,spec/knowledge/_inbox/done/spec-softdelete-escalation-alert-linkage.md -->

`POST /api/alert-resolve`：一次选择完成「动作执行 + 状态推进 + handled + 留痕」的处置闭环。

## 现行规则

- 端点 `POST /api/alert-resolve`（`core/dashboard/routes/alert_routes.py`）接受 `{project, alert_id, choice_id, note?}`，按序完成且对外表现为一次调用：(1) 校验告警存在且未 handled，按告警 `signal_type` 从注册表校验 `choice_id` 合法；(2) 执行 choice 映射的后端动作（复用 admin_actions 既有动词或裁决动词）；(3) 将 spec 状态机推进到该裁决的目标终态（含冻结解除、计数器处置、error 清理）；(4) 标记告警 handled 并落处置留痕。
- kind 差异：`kind=ESCALATION` 告警走既有 `AdminStore.mark_handled`（该方法仅匹配 ESCALATION）；`kind=SIGNAL` 记录（如 `build_artifact_paths_missing`）由端点经 `mark_signal_handled` 直接更新其 handled 族字段。
- 非法选择（choice_id 不在该信号的选项集）返回 400 级错误并说明合法选项集，spec 状态与告警 handled 状态均不变；对已 handled 告警重复提交返回冲突错误，不重复执行动作。
- 任一步失败返回结构化错误且不标记 handled；已执行的前序动作在错误信息中如实报告，不做虚假回滚声明，spec 保持可重试裁决。
- 人工失败路径零落痕：动作失败（共享执行器返回失败）分支只回 400——不写 disposition、不给告警打 `result=failed` 戳、不落 journal，落盘痕迹为零，事后排查只能对 `admin_alerts.json` 与文件态逐条比对；意外异常分支是失败面唯一的日志痕迹（`logger.exception` 落 journal，客户端只收固定文案、不外泄裸异常文本）。前端对失败统一 toast 固定文案「裁决执行失败，告警保持未处理，可调整后重试」，详细原因仅在告警卡片内联回显。带 `handled=False` 留痕的失败回执（`mark_signal_handled(handled=False, action_taken, result)`）是 Admin 链通道专用，人工端点不用。
- 成功处置在 `admin_alerts.json` 落一条 `kind=disposition` 记录：含 signal_type、spec、choice_id、note（人工备注，可空）与执行动作摘要；该记录对 dashboard admin 活动区可见，作为裁决审计轨迹。
- 人工下拉处置产生的留痕不依赖手写四段散文模板，满足「清除告警 ≠ 处置留痕」的治理要求。

## 代码锚点

- 端点：`core/dashboard/routes/alert_routes.py`（alert-resolve 复合序列、失败分支与幂等容忍）
- 共享执行器：`core/dashboard/data/admin_actions.py`（`execute_adjudication_choice` 只执行动作，handled 标记与 disposition 留痕由调用方按各自通道收口）
- 台账写入口：`core/admin_store.py`（`mark_handled` 仅匹配 ESCALATION、`mark_signal_handled` 仅匹配 kind=SIGNAL）
- 前端消费：`core/dashboard/static/src/hooks/useAlertAdjudication.tsx`（统一失败 toast 与告警卡片内联回显）
- 守卫测试：`tests/test_adjudication_choices.py`（端点闭环：成功 / 非法 choice / 重复处置 / 动作失败不假成功）

## 溯源

- 2026-09-27 add-human-adjudication-choices（spec/archive/2026-09-27-add-human-adjudication-choices） — 建立 alert-resolve 端点：选择即完整闭环、ESCALATION/SIGNAL 双 handled 通道、失败不虚假标记与结构化 disposition 留痕
- 2026-11-17 spec-softdelete-escalation-alert-linkage（spec/knowledge/_inbox/done/spec-softdelete-escalation-alert-linkage.md） — 折叠排查候选：人工失败路径零落痕语义（动作失败分支零写盘、异常分支 logger.exception 为唯一日志痕迹）、失败统一 toast 与卡片内联回显、留痕型失败回执 Admin 链通道专用分界
