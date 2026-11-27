# 提案：timelib 守卫回绿与已知失败基线治理

## 背景与问题

仓库级时间语义守卫（tests/test_timelib_guard.py，AST 静态扫描 core/ 全部生产代码与 fenixd.py 的五类禁用 datetime 模式）自 2026-11-16 22:06 起持续红约 4.6 天（至 2026-11-21 实测仍红）：

- 五处白名单外违例由三份独立交付同晚引入：
  - core/admin_monitor.py:4217、:4218、:4245 —— 零 tz 参数 datetime.fromtimestamp（epoch → 本地日分桶语义），引入提交 8a23833d03（evo-add-lane-stall-daily-budget-accounting，11-16 22:06）；
  - core/worktree_manager/stray_wip.py:354 —— 白名单外 datetime.fromisoformat，引入提交 6b9b94e62（evo-add-stray-wip-claim-reconcile，11-16 22:12）；
  - core/worktree_manager/mergeback.py:212 —— 白名单外 datetime.fromisoformat，引入提交 6239100a4（evo-scenario-exec-tree-isolation，11-16 23:41）。
- 守卫红状态下新增违例无法被区分发现，防回潮功能实质失效 4.6 天。
- 豁免惯性无回绿压力：tests/test_timelib_guard.py:206 的 [fenix-ignore:4b216478bc98] 注记（code-fix 车道「回归失败不复现」豁免标记）理由「当前 0 违例」自违例落地起失真仍持续豁免；批次收尾对守卫失败逐轮人工判读（code-fix-1795125181 收尾自述「判存量基线噪音」），无登记清单、无回绿时限。

## 目标

1. 五处违例收拢到 core/timelib.py 时间原语，守卫回绿（tests/test_timelib_guard.py 全绿）。
2. 建「已知红基线」结构化登记机制（KNOWN_RED_BASELINE）：带理由与到期日的临时登记清单，基线外违例即失败、基线条目超期即失败（回绿时限）、违例消失的基线条目须收缩。
3. 守卫测试内陈旧豁免注记的理由更新至反映回绿事实，消除误导。

## 非目标

- 不改 TIME_WHITELIST 语义：零豁免稳态棘轮与僵尸检测保持不变（五处均为 9-30 稳态后新增违例，回填白名单等于倒退棘轮，机制上也不允许）。
- 不动 fenix-ignore 注记约定与消费端（core/code_fix.py、core/agent_runner/maintenance_runs.py 不改）。
- 不改 timelib 六函数既有契约（API 只许 ADDITIONAL 扩展）。