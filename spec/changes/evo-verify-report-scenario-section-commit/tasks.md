## Deliverables

```yaml
- path: core/pm_engine/verification/scenario_gate.py
  kind: modify
- path: core/verify_report.py
  kind: reference
- path: tests/test_verification_report_commit.py
  kind: modify
```

## 1. 场景段写盘即入库

- [x] 1.1 core/pm_engine/verification/scenario_gate.py：_render_scenario_change_section_to_report 的原子写回（约 :548）成功分支后，函数内 import 调用 core.verify_report 的 _commit_verification_report(project_root, spec_name, logger)，复用既有 pathspec 单文件幂等提交器
- [x] 1.2 core/pm_engine/verification/scenario_gate.py：失败降级——提交器返回失败或抛错仅记 WARNING（透传既有文案风格），渲染写盘结论与验证主流程不变；非 git 项目沿用提交器内置静默跳过

## 2. 测试

- [x] 2.1 tests/test_verification_report_commit.py：新增场景段提交用例——种子报告加桩 pipeline 上下文（_context.project_root/logger 与 _last_scenario_diff/_last_freeze_owner 归属戳），调用真实渲染函数，断言 HEAD 包含小节且该 pathspec 对 HEAD 干净
- [x] 2.2 tests/test_verification_report_commit.py：隔离用例——其他 spec 的 staged 草案与已跟踪文件未暂存修改在场时，场景段提交仅入库报告文件本身
- [x] 2.3 tests/test_verification_report_commit.py：幂等用例——小节已在库后二次触发无新提交且零 WARNING
- [x] 2.4 回归自检：tests/test_pm_verification.py、tests/test_pm_recovery.py、tests/test_verify_parallel_backoff.py、tests/test_verify_report_gate.py、tests/test_verify_scenarios.py、tests/test_facade_delegation_contract.py 全绿（存量 MagicMock 桩不受扰；末项经 engine.py:264 门面映射桩本函数委托名，属改动邻接面）