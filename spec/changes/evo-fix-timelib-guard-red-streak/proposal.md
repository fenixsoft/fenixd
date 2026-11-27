# 提案：timelib 守卫回绿与已知失败基线治理

## 背景与问题

仓库级时间语义守卫（tests/test_timelib_guard.py，AST 静态扫描 core/ 全部生产代码与 fenixd.py 的五类禁用 datetime 模式）自 2026-11-16 22:06 起持续红约 4.6 天（至 2026-11-21 实测仍红）：

- 五处白名单外违例由三份独立交付同晚引入：
  - core/admin_monitor.py:4217、:4218、:4245 —— 零 tz 参数 datetime.fromtimestamp（epoch → 本地日分桶语义），引入提交 8a23833d03（evo-add-lane-stall-daily-budget-accounting，11-16 22:06）；
  - core/worktree_manager/stray_wip.py:354 —— 白名单外 datetime.fromisoformat，引入提交 6b9b94e62（evo-add-stray-wip-claim-reconcile，11-16 22:12）；
  - core/worktree_manager/mergeback.py:212 —— 白名单外 datetime.fromisoformat，引入提交 6239100a4（evo-scenario-exec-tree-isolation，11-16 23:41）。
- 守卫红状态下新增违例无法被区分发现，防回潮功能实质失效 4.6 天。
- 豁免惯性无回绿压力：tests/test_timelib_guard.py:206 的 [fenix-ignore:4b216478bc98] 注记（code-fix 车道「回归失败不复现」豁免标记）理由「当前 0 违例」自违例落地起失真仍持续豁免；批次收尾对守卫失败逐轮人工判读（code-fix-1795125181 收尾自述「判存量基线噪音」），无登记清单、无回绿时限。

> **2026-11-27 复评修订（世界线变更）**：守卫红窗已由外部 code-fix batch 提交 4fec3994c（2026-11-21 15:02，items: regression-fix-timelib-guard）终结——五处违例已收拢进 timelib：admin_monitor 日桶裸 fromtimestamp → timelib.from_epoch（UTC 日桶，对齐「存储与计算层 aware UTC」分层约定）、mergeback/stray_wip 裸 fromisoformat → timelib.parse_ts。复评实测：守卫 18 passed、TIME_WHITELIST 零豁免稳态保持、:206 注记「当前 0 违例」恢复为事实、调用方定向回归（test_lane_stall_accounting / test_timelib）48 passed。因此目标 1 的迁移工作已由外部达成（本 SPEC 只保留验证性确认，不重复迁移）；目标 3 的注记失真已自愈。本 SPEC 剩余主体为目标 2（KNOWN_RED_BASELINE 机制，实测尚未存在）与目标 3 的登记通道补记。

## 目标

1. （已由外部 4fec3994c 达成）五处违例收拢到 core/timelib.py 时间原语，守卫回绿（tests/test_timelib_guard.py 全绿）——本 SPEC 仅保留验证性确认（核对收拢形态与守卫绿），不重复迁移、不改写已合入语义。
2. 建「已知红基线」结构化登记机制（KNOWN_RED_BASELINE）：带理由与到期日的临时登记清单，基线外违例即失败、基线条目超期即失败（回绿时限）、违例消失的基线条目须收缩。
3. 守卫测试内 :206 豁免注记随 KNOWN_RED_BASELINE 落地补记「后续已知红走基线登记」通道说明（原「当前 0 违例」失真已随外部回绿自愈，注记现为事实表述，其余文本不动）。

## 非目标

- 不改 TIME_WHITELIST 语义：零豁免稳态棘轮与僵尸检测保持不变（五处均为 9-30 稳态后新增违例，回填白名单等于倒退棘轮，机制上也不允许）。
- 不动 fenix-ignore 注记约定与消费端（core/code_fix.py、core/agent_runner/maintenance_runs.py 不改）。
- 不改 timelib 六函数既有契约（API 只许 ADDITIONAL 扩展）。
- 不重开日桶时区语义之争：admin_monitor 日桶已按外部修复以 timelib.from_epoch（UTC 日桶）合入并对齐 aware UTC 分层约定；本 SPEC 不新增 local_date，「epoch → 本地日分桶」如需引入另行立项（行为变化按 timelib-callsite-migration「迁移等价替换纪律」不走顺手修改）。