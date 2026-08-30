# Tasks: fix-budget-counting-semantics

实现依据（实施 agent 必读）：
- 能力定义 `specs/fail-counter-budget/spec.md`（MODIFIED）；设计决策 design.md D1-D3
- 计数点：`.fenix/core/pm_engine.py` `_run_agent_worker` implementer 启动处（`实现尝试预算计数 +1` 日志约 3450 行附近）；死亡判定：恢复链路确认无收工结果处
- STATE 写回：`.fenix/core/state_machine.py`（文件锁与 `_` 前缀机制）
- 夹具：interaction-contract 复盘（used=2/4 连续两次的丢失证据、死亡 run 序列）

## 1. 原子计数原语

- [ ] 1.1 `state_machine.bump_impl_budget(spec, delta) -> int`：文件锁内读改写并回读校验（不匹配重试一次 + 审计日志），delta=-1 下限 0
- [ ] 1.2 启动计数点与死亡豁免点统一改走该函数；移除既有非原子读改写

## 2. 死亡豁免

- [ ] 2.1 恢复链路确认 run 异常死亡（无收工结果）时：`bump_impl_budget(spec, -1)` + `_budget_exempt_runs` 侧车递增 + 审计日志
- [ ] 2.2 侧车达 6（常量 `BUDGET_EXEMPT_ALERT_THRESHOLD`）→ 一次性提醒级告警（幂等标记 `_exempt_alerted`），不冻结

## 3. 对账

- [ ] 3.1 merge 成功/守卫放行后回读 used 与正常收工 run 数比对，偏差记 WARNING（不自动改数）

## 4. 单元测试

- [ ] 4.1 覆盖：死亡 run 豁免（used 回退 + 侧车递增）；死亡侧车 6 次一次性告警；正常失败不豁免；并发双增量不丢失（线程级模拟）；回读校验重试；下限 0
- [ ] 4.2 用 interaction-contract 真实序列（2 死亡 + 2 正常）作夹具：终态 used 应为 2 而非 4

## 5. 验证与打包

- [ ] 5.1 运行 `python3 -m pytest tests/ -v` 确认无回归
- [ ] 5.2 执行 `bash scripts/package.sh` 生成最新扩展包
