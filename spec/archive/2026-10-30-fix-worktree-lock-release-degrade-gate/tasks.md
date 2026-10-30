## Deliverables

```yaml
- path: core/worktree_manager/lifecycle.py
  kind: modify
- path: core/worktree_manager/locks.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_worktree_lock_terminal_release.py
  kind: new
```

## 1. 锁记录 owner 化与终态释放

- [x] 1.1 `core/worktree_manager/lifecycle.py`：spec 锁记录从集合改为携带 owner run_id 的映射，`create()` 增可选 owner_run_id 入参并记录当前 run_id（core/agent_runner/runner.py:4223/4282 调用点传 attempt run_id，缺省 None 维持现状）；扩展既有 `release_spec_lock(spec, agent_type)`（lifecycle.py:530）增可选 owner 参数——传 owner 时一致才 discard，不一致 no-op + DEBUG 留痕，不传维持既有幂等语义（code-fix defer 车道零改动）；`core/worktree_manager/locks.py` `_register_spec_locks` 登记点同步适配（owner=None）；同文件既有读点（already active 日志、early give-up 判定）同步适配
- [x] 1.2 `core/agent_runner/runner.py` run 终态收尾链挂释放：失败类终态（框架终态单源 `RUN_TERMINAL_EVENT_TYPES`：非成功 result / error / interrupted / cancelled / frozen-terminated / gate-blocked）落账处调用 release_spec_lock（成功终态不调用；原地重试中间弃置件 superseded 不挂释放——退避窗口摘锁重开双派发窗口，该场景由 2.1 清扫兜底）；单测（tests/test_worktree_lock_terminal_release.py 新建）覆盖「终态后同 agent_type 立即可 acquire」与「owner 不符释放为 no-op」

## 2. acquire 陈锁存活清扫

- [x] 2.1 acquire「already active」早退段：早退前核对持锁 run 存活性（run 记录 `.fenix/runs/<run_id>.jsonl` 末行属死亡判据集 `RUN_TERMINAL_EVENT_TYPES` ∪ {"superseded"}——弃置件即死、为 10-26 事故形态；或记录不存在且锁龄超过 early give-up cap 1200s）——确认死亡则 discard + WARNING 并继续本次 acquire；记录在飞且末行非死亡判据行时维持既有 early give-up；owner=None 登记锁退回锁龄判据
- [x] 2.2 单测：①死锁主（记录末行为终态行或 superseded 弃置件）→ 清扫放行；②在飞持锁主 → 维持早退不错杀；③记录缺失且窗口已过 → 清扫放行；④owner=None 登记锁年轻 → 不清扫

## 3. 连续降级熔断

- [x] 3.1 `core/pm_engine/engine.py` 降级决策点：spec 级连续降级计数（持久化于 spec STATE 条目，对齐 `_verify_fail_rounds` / `_env_block_rounds` 字段先例——实例/模块级计数已被 engine.py:201-205 注释证伪）——首次降级放行 + WARNING；连续第 2 次 NOT 派发 legacy，改 blocked + human-escalation-alert（文案含两次降级原因链与建议动作）
- [x] 3.2 计数清零接线：验证轮成功推进 / admin 处置复位 / 人工解冻（unfreeze_spec 清零集）三处清零；单测覆盖「首次放行、第二次熔断、解冻后重获降级机会」
- [x] 3.3 unfreeze_spec 计数清零集扩展的既有用例回归（tests/ 既有 unfreeze/验证计数用例全绿）

## 4. 回归

- [x] 4.1 既有 worktree 相关测试全绿（锁互斥、继承认领、adaptive backoff 行为不回归；含 code-fix defer 车道 release_spec_lock 既有 caller 与 has_active_lock 消费点 engine.py `_worktree_locks_released`）
- [x] 4.2 既有 engine 降级路径测试全绿（首次降级语义逐位一致）
