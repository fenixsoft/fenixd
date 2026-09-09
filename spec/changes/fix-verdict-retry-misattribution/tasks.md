# Tasks: fix-verdict-retry-misattribution

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: tests/test_verdict_evidence_taxonomy.py
  kind: modify
- path: tests/test_verdict_retry_misattribution.py
  kind: new
```

## 1. frozen 文案常量同源

- [ ] 1.1 core/agent_runner/runner.py：frozen 门 error 文案抽为模块级导出常量（如 `FROZEN_TERMINATED_ERROR_PREFIX`），frozen 门与取消旗标路径的 error 构造均引用该常量；对外文案不变
- [ ] 1.2 core/pm_engine/verification.py：frozen 判定（含首轮与重试路径）引用 1.1 常量，删除硬编码字面量；取消判定沿用 `AgentRunResult.cancelled` 结构化字段

## 2. _verify_verdict_evidence 语义化改造

- [ ] 2.1 core/pm_engine/verification.py：返回值改为 `{"ok", "cause", "violations", "dispatch_error"}`；cause 枚举 `pass/violations/dispatch_frozen/dispatch_cancelled/dispatch_failed/dispatch_exception/report_missing`；首轮合规路径 cause=`pass`
- [ ] 2.2 重试路径三分支拆分：frozen/取消 → `dispatch_frozen`/`dispatch_cancelled` 零写入早退（仅 logger.info 留痕，不调 update_spec、不发告警）；其它 `success=False` → `dispatch_failed` 携带原始 error；`run_planner` 抛异常 → `dispatch_exception` 立即返回，禁止落至 `load_report` 复读旧文件、禁止打「重试后仍不合规」ERROR
- [ ] 2.3 `violations` 路径保留既有语义（调用方 blocked + 告警），返回值携带 `validate_report` 原始 violations 明细；重试成功但 report 不可读 → `report_missing`
- [ ] 2.4 全库 grep `_verify_verdict_evidence` 确认调用点全部适配新返回形状，无第三方消费遗漏

## 3. 调用方分支处置

- [ ] 3.1 core/pm_engine/verification.py 阶段3+ 采纳处：按 cause 分支——`dispatch_frozen`/`dispatch_cancelled` 零写入零告警；`dispatch_failed` 温和告警（不冒充二次违规，不发 verdict_evidence_invalid）；`violations` 保留 blocked + verdict_evidence_invalid（evidence 增强）；未知 cause 按 violations 保守处置 + ERROR 留痕
- [ ] 3.2 首轮 `judge_result.success=False` 分支补 frozen 分支（cancelled 与 circuit-open 分支之后）：INFO 留痕 + return，不落 `raise RuntimeError`
- [ ] 3.3 `verdict_evidence_invalid` 告警 evidence 携带 violations 明细（scenario_id + reason，>20 条截断注明总数）；STATE error 文案按 cause 生成，「重试一次仍不合规」表述仅存在于 violations 路径

## 4. 失败历史侧车与升级告警透传

- [ ] 4.1 失败历史侧车：`.fenix/verify-progress/<spec>/fail_history.json` 每轮裁决采纳失败原子追加 `{round, cause_type, failed_scenarios}`；spec 进入终态清空；写盘失败静默降级（分型 unknown，不阻断闸门）
- [ ] 4.2 `verify_fail_escalation` 告警 evidence 携带失败分型（evidence-invalid / real-bugs / repeat / unknown）与相邻轮 failed_scenarios diff（新增/消失/持留）；`fail_rounds` 计数逻辑本身不改
- [ ] 4.3 轮次口径命名区分：打回链文案统一「原地打回第 N 轮」、升级闸门文案统一「升级闸门连续失败第 N 轮」，清理裸「第 N 轮」表述

## 5. 测试与回归

- [ ] 5.1 tests/test_verdict_retry_misattribution.py（new）：四组夹具——frozen 拦截（零写入零告警断言，复放 09:28 场景）/ 取消拦截同语义 / 异常早退（断言不复读旧文件、无假 ERROR）/ 真二次违规（blocked + 告警 evidence 含 violations 断言）；另含 dispatch_failed 与 violations 分离、未知 cause fail-closed、首轮 frozen 让位三组
- [ ] 5.2 tests/test_verdict_evidence_taxonomy.py：现行「二次失败 → blocked + 告警」断言限定为 violations 路径；返回形状适配
- [ ] 5.3 既有回归全绿：test_pm_promotion_gate.py（judge 链）、test_pm_verification.py、test_verdict_visibility.py 无回归
