# Design: fix-verdict-retry-misattribution

## Context

2026-09-08 事故链（日志可复放）：judge run 在飞 27.7min 期间用户人工冻结 spec → run 完成后 `_verify_verdict_evidence` 首轮校验失败（流截断致 10 场景缺增强）→ 发起重试 → `runner.py` attempt 顶部 frozen 门拦截（不派发，返回 `success=False, error="spec frozen — auto-retry terminated"`）→ 该失败被并入「二次不合规」返回 False → 调用方产出 `verdict_evidence_invalid` critical 假告警 + 伪 blocked + 硬编码文案。同函数内另有三条同型坍缩路径（异常复读旧文件 / 派发失败 / 产物丢失），以及升级闸门裸计数致误置冻结、告警缺 violations 明细致调查带偏。

约束：不新增配置键；不动 `fail_rounds` 计数逻辑与 `add-judge-artifact-gate` 已落地的三道防线；`cause=violations` 路径对外行为与现状一致（blocked + 告警保留）。

## Goals / Non-Goals

- Goals：四条 False 路径语义拆分；frozen/cancelled 静默让位；失败信息（violations、分型、diff）结构化透传至告警与 STATE
- Non-Goals：不改 judge prompt 契约文本（归因已证明不在文本）；不做失败指纹收敛判定（误置冻结的完整治理，另立）；不改 `runner.py` frozen 门行为（拦截本身正确）

## Decisions

### D1. 返回形状：结构化 dict，异常不做控制流

`_verify_verdict_evidence` 返回 `{"ok": bool, "cause": str, "violations": list, "dispatch_error": str}`：

- `cause=violations`：重试 judge 成功返回且新产物仍违规（唯一真·二次违规），`ok=False`，violations 携带 `validate_report` 原始明细
- `cause=dispatch_frozen` / `dispatch_cancelled`：重试派发被 frozen 门/取消旗标拦截，`ok=False`
- `cause=dispatch_failed`：其它派发失败（网关拒绝、预算闸门等），`ok=False`，dispatch_error 带原始 error
- `cause=dispatch_exception`：`run_planner` 抛异常，`ok=False`——**立即返回，禁止落至 `load_report` 复读旧文件**（现路径 Y 的假 ERROR 根除）
- `cause=report_missing`：重试成功但 report.json 不可读
- 首轮合规（`result["ok"]`）路径 cause 固定 `"pass"`

选 dict 而非 NamedTuple/异常：与 `validate_report` 返回风格一致；调用方既有分支（cancelled/circuit-open）均为值分支，风格统一。

### D2. 让位语义：零写入

`dispatch_frozen` / `dispatch_cancelled` 路径**不调用 `update_spec`、不发任何告警**，仅 `logger.info` 留痕（含 cause 与拦截来源）。理由：frozen/取消旗标均为人式决策载体，spec 已在人工手里；`update_spec` 带 `status` 会顺带清 `_cancelled_hold`（fix-cancel-holdstate-recovery D4），让位路径完全不触状态机即天然规避该副作用。

### D3. frozen 判定：文案常量同源

`runner.py` frozen 门 error 文案与 `verification.py` 匹配逻辑共用导出常量（如 `FROZEN_TERMINATED_ERROR_PREFIX = "spec frozen"`），防文案改动使匹配失效。取消旗标路径沿用 `AgentRunResult.cancelled` 结构化字段（非字符串匹配）。

### D4. 首轮 judge_result 补 frozen 分支

阶段3 首轮 `if not judge_result.success:` 块内、cancelled 分支后新增 frozen 分支：INFO 留痕 + return（spec 冻结时在飞 run 完成的正确处置是让位，与 cancelled「保持 testing 原状只写 error」及 circuit-open「抑制」同型）。`raise RuntimeError` 兜底路径不再吞 frozen。

### D5. violations 透传

`cause=violations` 时：`verdict_evidence_invalid` 告警 evidence 追加 violations 明细（每条 `scenario_id + reason`，截断保护 ≤20 条）；STATE error 由调用方按 cause 生成，仅 violations 文案保留「重试一次仍不合规」表述（此时重试确实发生过），其余 cause 不产出该告警/文案。

### D6. 失败分型与轮间 diff：失败历史侧车

新增运行时侧车 `.fenix/verify-progress/<spec>/fail_history.json`（每轮裁决采纳失败时原子追加 `{round, cause_type, failed_scenarios}`；spec 转出 bug-found/verified 终态时清空）。`verify_fail_escalation` 触发处读侧车生成分型：

- `evidence-invalid`：该轮 cause 为证据校验不合规
- `real-bugs`：该轮为 bug-found（真产品/测试缺陷）
- `repeat`：失败场景集与上一轮完全相同（相同集合连续出现即升级闸门冻结的「无进展」信号，为 2026-09-08T19:12 误置冻结提供可识破依据）

告警 evidence 附相邻两轮 `failed_scenarios` diff（新增/消失/持留）。fail_history 属 `.fenix/` 运行时产物，Deliverables 声明 `reference`。

### D7. 轮次口径命名区分

两套计数器语义不同、均保留，文案显式命名：「原地打回第 N 轮」（bug-found 打回链）与「升级闸门连续失败第 N 轮」（fail_rounds），杜绝同日「第 2 轮」与「3 轮」并存的表述歧义。

## Risks / Trade-offs

- `[中]` 既有测试断言更新：`test_verdict_evidence_taxonomy.py` 等处「二次失败 → blocked + 告警」断言需限定为 `cause=violations` 路径；frozen/cancelled/异常三路径新增夹具
- `[低]` fail_history 写盘失败：静默降级（缺侧车 → 分型标注 unknown，不阻断升级闸门）
- `[低]` cause 分支遗漏：调用方对未知 cause 按 `violations` 保守处置并 ERROR 留痕（fail-closed 不静默放行）

## Migration Plan

单提交原子切换（返回形状同时改实现与全部调用点，全库 grep `_verify_verdict_evidence` 确认无第三方调用）；无数据迁移，fail_history 首轮失败时自建。

## Open Questions

- 无（失败指纹收敛判定已在探索中明确为 Non-Goal，观察分型透传效果后另议）
