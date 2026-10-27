## Deliverables

```yaml
- path: core/worktree_manager/lifecycle.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: tests/test_worktree_lock_terminal_release.py
  kind: new
```

## 1. 锁记录 owner 化与终态释放

- [ ] 1.1 `core/worktree_manager/lifecycle.py`：spec 锁记录从集合改为携带 owner run_id 的映射，acquire 记录当前 run_id；新增 `release_spec_lock(spec, agent_type, owner_run_id)`——owner 一致才 discard，不一致 no-op + DEBUG 留痕；同文件既有读点（already active 日志、early give-up 判定）同步适配
- [ ] 1.2 run 终态收尾链挂释放：superseded / error / failed / frozen-terminated 终态落账处调用 release_spec_lock（成功终态不调用）；单测（tests/test_worktree_lock_terminal_release.py 新建）覆盖「supersede 后同 agent_type 立即可 acquire」与「owner 不符释放为 no-op」

## 2. acquire 陈锁存活清扫

- [ ] 2.1 acquire「already active」早退段：早退前核对持锁 run 存活性（run 记录 `.fenix/runs/<run_id>.jsonl` 含终态行，或记录不存在且派发窗口已过）——确认死亡则 discard + WARNING 并继续本次 acquire；判据不确定维持既有 early give-up
- [ ] 2.2 单测：①死锁主（记录含终态行）→ 清扫放行；②在飞持锁主 → 维持早退不错杀；③记录缺失且窗口已过 → 清扫放行

## 3. 连续降级熔断

- [ ] 3.1 `core/pm_engine/engine.py` 降级决策点：spec 级连续降级计数——首次降级放行 + WARNING；连续第 2 次 NOT 派发 legacy，改 blocked + human-escalation-alert（文案含两次降级原因链与建议动作）
- [ ] 3.2 计数清零接线：验证轮成功推进 / admin 处置复位 / 人工解冻（unfreeze_spec 清零集）三处清零；单测覆盖「首次放行、第二次熔断、解冻后重获降级机会」
- [ ] 3.3 unfreeze_spec 计数清零集扩展的既有用例回归（tests/ 既有 unfreeze/验证计数用例全绿）

## 4. 回归

- [ ] 4.1 既有 worktree 相关测试全绿（锁互斥、继承认领、adaptive backoff 行为不回归）
- [ ] 4.2 既有 engine 降级路径测试全绿（首次降级语义逐位一致）
