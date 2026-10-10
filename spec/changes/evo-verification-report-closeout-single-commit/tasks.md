## Deliverables

```yaml
- path: core/verify_report.py
  kind: modify
- path: core/pm_engine/verification/report_gate.py
  kind: modify
- path: core/pm_engine/verification/scenario_gate.py
  kind: reference
- path: tests/test_verification_report_commit.py
  kind: modify
- path: spec/knowledge/domains/verify-pipeline/verification-report.md
  kind: modify
```

## 1. 闸门合并提交

- [ ] 1.1 core/verify_report.py：`ensure_verification_report` 增加可选 pre_commit 回调参数（默认 None、签名向后兼容），present/resynthesized/synthesized 三个放行出口均在 `_commit_verification_report` 前以 try/except Exception 执行回调（异常仅 WARNING、不阻断放行）；未传回调时行为与现状逐字等价。
- [ ] 1.2 core/pm_engine/verification/report_gate.py：`_ensure_verification_report` 函数内延迟导入 scenario_gate 的 `_render_scenario_change_section_to_report`，以闭包（捕获 pipeline、spec_name）注入 pre_commit，使闸门单次提交含报告本体与「本轮场景集变更」小节；覆盖 pipeline._apply_verified(:1316)、_apply_bug_found(:1150) 与 legacy.py(:408、:603) 四个采纳调用点。
- [ ] 1.3 core/pm_engine/verification/pipeline.py：确认 :1408/:1232 末尾渲染点保留为兜底——闸门已合并提交时按「标题已存在即跳过」幂等判定零成本跳过、不产生第二次提交；push 收口（approve_push 直调提交器）与渲染函数直调路径行为不变。
- [ ] 1.4 spec/knowledge/domains/verify-pipeline/verification-report.md：改写「场景段写盘即入库」与「入库挂点链」两条规则为「场景段渲染合并进闸门 pre-commit 挂点、采纳流程内报告相关提交至多一次」，溯源段补记本 spec。

## 2. 测试

- [ ] 2.1 tests/test_verification_report_commit.py：新增合并形态用例——synthesized 与 present 出口下闸门放行后提交计数恰 +1，HEAD 内容同时含报告本体与「本轮场景集变更」，pathspec 严格单文件、其它 spec staged 草案与无关修改不被卷入；pre_commit 回调抛异常时闸门仍放行、报告本体照常入库、WARNING 恰一条；闸门放行后模拟采纳尾段二次渲染，提交计数不增、WARNING 零新增。
- [ ] 2.2 tests/test_verification_report_commit.py：既有 TestScenarioSectionCommit（直调渲染单文件提交、幂等跳过）与 TestNonGitProjectSilentSkip 全部保持通过；tests/test_push_closeout_report_commit.py 全绿（push 收口路径零回归）。