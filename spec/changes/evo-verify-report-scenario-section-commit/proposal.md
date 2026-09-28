# verify-report-scenario-section-commit

## Why

验证裁决采纳流程内存在一个入库次序缝：报告闸门先提交（pipeline.py:1120/:948 → verify_report.py:888 三出口），状态 transition 之后场景段渲染才把「本轮场景集变更」小节写进报告文件（pipeline.py:1194/:1034 → scenario_gate.py:499/:548），此后再无任何提交点。实测 11 个已跟踪报告带未暂存小节（合计 75 行纯新增），其中包括 evo-add-verification-report-commit-on-write 自己的报告（+5 行，正文「场景集与持久化集一致，无变更」）——盲区直接自证。这些场景集演进记录在工作区误操作或重建下可丢，且随被验证 spec 数增长持续扩大。

## What Changes

1. scenario_gate.py 的 _render_scenario_change_section_to_report 原子写回成功后，立即复用 core/verify_report.py:805 的 _commit_verification_report 做该报告单文件的 pathspec 幂等提交。
2. 失败降级：git 失败仅 WARNING，不影响渲染写盘结论与验证主流程；非 git 项目静默跳过。
3. 幂等：小节已在库后再触发无新提交零 WARNING；每份报告至多一段（:541 幂等判重），故额外提交至多一次。
4. 不回填存量 11 份（沿 commit-on-write 非目标先例，归档兜底承接）；不改放行出口与闸门行为。

## Non-Goals

- 不做历史回填（存量 11 份未入库小节留给归档兜底）。
- 不改 ensure_verification_report 三出口与四个放行调用点行为。
- 不动 legacy 路径（该路径不渲染场景段，无此缺口）。
- 不改渲染函数 render_change_section 本身。

## Impact

- Specs: specs/verification-report/spec.md（ADDED：场景段落盘即入库、失败降级）
- Code: core/pm_engine/verification/scenario_gate.py（写回后接入提交器）、core/verify_report.py（reference，复用 _commit_verification_report）
- Tests: tests/test_verification_report_commit.py（新增场景段提交/隔离/幂等三组用例）
- 行为变化：采纳流程结束后报告文件（含场景段）保证已入库；git 失败 WARNING 降级。