# Tasks: refactor-test-structure

## 1. 拆分准备

- [x] 1.1 生成拆分前基线：`pytest --collect-only -q` 用例数 + 全量结果快照；盘点 test_core.py/test_dashboard.py 的类与用例归属，产出与 design D1 对齐的拆分清单

## 2. 拆分 test_core.py（每模块：整类/整函数搬移 + import 调整 → 单模块单跑通过 → 用例数守恒 + 全量通过 → 独立 commit）

- [x] 2.1 拆出 PMEngine 侧模块：test_pm_dispatch.py、test_pm_family.py、test_pm_budget.py
- [x] 2.2 拆出 PMEngine 侧模块：test_pm_verification.py、test_pm_recovery.py、test_pm_reporting.py
- [x] 2.3 拆出 AgentRunner 侧模块：test_runner_prompt.py、test_runner_provider.py、test_runner_liveness.py、test_runner_token.py、test_runner_v2.py
- [x] 2.4 拆出平台侧模块：test_state_machine.py、test_config.py、test_event_bus.py
- [x] 2.5 共享夹具/helper 归位 tests/helpers.py；删除空壳 test_core.py

## 3. 拆分 test_dashboard.py（同上纪律）

- [x] 3.1 拆出 test_dashboard_api.py、test_dashboard_data.py、test_dashboard_watcher.py；删除空壳 test_dashboard.py

## 4. 增量测试选择

- [x] 4.1 实现 bin/test_for.py：AST import 链推导（含函数内局部 import，传递深度 3 层）、--dry-run/--all、无命中回退全量提示
- [x] 4.2 建立 tests/test_map.yaml 显式映射（dashboard 静态资源、STATE.md 等间接耦合）与失效映射告警
- [x] 4.3 实测增量入口：对若干真实修改文件验证推导正确性（直接依赖、传递依赖、无命中回退三场景）

## 5. 收尾验证

- [x] 5.1 全量 pytest 对照基线（用例数守恒、结果不劣于 912 passed + 1 环境性失败）；审计全部 commit 变更文件清单确认被测代码零修改

## 验证修复

> 2026-09-01 管理员处置留痕（blocked 预算冻结 + 验证 16/16 全场景同因失败）：原场景集为模板缺陷——
> 16 个场景全部点击 dashboard 中不存在的 data-testid（nav-tests / tool-test-for / tool-test-map 等
> 「Tests 管理页」从未存在于任何界面），对本 spec（纯测试基础设施重构，交付物在 CLI/pytest 层，
> proposal 明确不改被测代码）而言整轮必失败，属伪失败而非产品缺陷。
> 处置：16 个场景保持 ID 与依赖图不变，定义改写为生产 dashboard（8787）真实 UI 交互与 API 冒烟
> （选择器均经 core/dashboard/static 源码核对；对齐 refactor-test-callsites 先例 commit 39931e9），
> 移除随他 spec 合并持续漂移的视觉基线（失效基线归档 baselines_stale_20260901），并按验证引擎语义
> playwright 预检 16/16 通过。原始场景与基线备份于 .fenix/admin-backup/refactor-test-structure-20260901/。
> 本段为纯修复留痕，不声明新交付，planner 不得扩容。
