# Proposal: fix-verdict-retry-misattribution

## Why

2026-09-08 add-draft-promotion-gate 事故：judge run 在飞期间用户人工冻结 spec，run 完成后裁决证据校验失败发起重试，重试派发被 frozen 门拦截（`success=False, error="spec frozen — auto-retry terminated"`），`_verify_verdict_evidence` 将「派发被拦」与「judge 二次违反证据契约」坍缩为同一个布尔 False 返回，调用方按后者处置——产出 `verdict_evidence_invalid` critical 假告警 + 伪 blocked + 硬编码 error 文案「重试一次仍不合规」（该重试从未发生）。假告警直接误导当日事故调查（归因指向 spec 文本契约表述，实为框架接缝缺陷），且任何用户在任何 judge run 在飞期间冻结 spec 都会复现同一路径。

同型缺口三处：① 重试路径中 `run_planner` 抛异常时 `re_judge=None` 不早退，继续 `load_report` 复读第一轮违规的旧文件并打出「重试后仍不合规」假 ERROR；② 首轮 `judge_result.success=False` 分支有 cancelled 与 provider-circuit-open 两个专门分支，唯独缺 frozen 分支（会落入 `raise RuntimeError`）；③ `verify_fail_escalation` 告警只有裸 `fail_rounds` 计数，不区分「证据不合规 / 真 bug / 与上轮同失败集」，2026-09-08T19:12 升级闸门据此对根因已修复的 spec 误置冻结（admin 处置已确诊「属误置冻结」）。violations 数据本为结构化（scenario_id + reason），但从未进入任何告警。

## What Changes

- `_verify_verdict_evidence` 返回值从布尔改为语义化结构（ok / cause / violations / dispatch_error），四条 False 路径拆为六个 cause：`violations`（真二次违规）、`dispatch_frozen`、`dispatch_cancelled`、`dispatch_failed`（网关拒绝/预算闸门等）、`dispatch_exception`（异常早退）、`report_missing`
- frozen / cancelled 派发失败 = 人工已接管 → 框架静默让位：不写 blocked、不发 `verdict_evidence_invalid`、不改任何状态，INFO 留痕
- 首轮 `judge_result` 失败分支补 frozen 分支，与既有 cancelled / circuit-open 分支语义对齐
- `verdict_evidence_invalid` 告警仅由 `cause=violations` 触发，evidence 携带结构化 violations 明细；STATE error 按 cause 生成，不再引用未发生的重试
- `verify_fail_escalation` 告警 evidence 携带失败分型（证据不合规 / 真 bug / 同失败集重复）与相邻轮失败场景集 diff；告警文案显式区分「bug-found 原地打回计数」与「升级闸门计数」两种轮次口径

## Capabilities

### 新增能力

- `verdict-failure-semantics`：裁决证据校验失败的语义化分类与分支处置（frozen/cancelled 让位、异常早退、派发失败与真违规分离、首轮 frozen 对称分支）
- `verdict-failure-passthrough`：裁决失败信息的结构化透传（violations 明细入告警、失败分型与轮间 diff、error 文案按 cause 生成、轮次口径区分）

## Impact

- 代码：`core/pm_engine/verification.py`（`_verify_verdict_evidence` + 阶段3+ 采纳处 + 首轮 judge_result 分支）
- 测试：`tests/test_verdict_evidence_taxonomy.py`（现行「二次失败 → blocked」断言更新）、新建 cause 分支夹具测试
- 行为兼容：`cause=violations` 时对外行为与现状一致（blocked + 告警保留，仅 evidence 增强）；frozen/cancelled/异常路径行为收紧为静默让位；不新增配置键；不动 `fail_rounds` 计数逻辑本身（只改透传展示）
