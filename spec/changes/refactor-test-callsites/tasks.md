# Tasks: refactor-test-callsites

## 1. 迁移准备

- [x] 1.1 盘点 tests/ 全部门面委托调用点，产出 文件→调用点 清单与分批计划（按组件耦合面从小到大，test_core.py 最后）

## 2. 分批迁移（每批：改写调用点 → 批内文件单跑通过 → 全量 pytest 通过 → 独立 commit）

- [x] 2.1 批 1：单组件测试文件（test_family_governor、test_fail_counter_budget、test_dispatch_aging、test_repair_* 等）
- [x] 2.2 批 2：agent_runner 侧测试文件（test_agent_runner、test_provider_*、test_run_lifecycle_governance、test_cost_observability、test_admin）
- [x] 2.3 批 3：验证链路测试文件（test_verify_report_gate、test_verify_scenarios、test_verdict_evidence_taxonomy、test_interaction_contract、test_deliverable_gate、test_env_sanity_gate、test_inplace_bug_repair 等）
- [x] 2.4 批 4：test_core.py（最后迁移）
- [x] 2.5 批 5：残余文件（test_dashboard、test_alert_lifecycle、test_recovery_legacy 等扫尾）

## 3. 门面收缩

- [x] 3.1 grep 全仓库确认零调用者的委托方法清单，从门面删除（有生产调用者的一律保留），独立 commit
- [x] 3.2 最终验证：全量 pytest（不劣于基线）+ fenixd.py/core/dashboard import 与调用零修改确认

## 验证修复（第 2 轮失败）

- [x] 阅读 `openspec/changes/refactor-test-callsites/verification-report.md`，定位「真实产品 Bug」并修复（已完成于 209c8bb：分析确认浏览器验证场景缺陷非本 SPEC 引入，Python 测试通过）
- [x] 修复后重跑验证确认通过（209c8bb 全量 pytest 通过；管理员 2026-09-01 修正 11 个失效场景模板后重验）
