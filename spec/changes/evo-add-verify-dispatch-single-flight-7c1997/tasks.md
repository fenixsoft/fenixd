## Deliverables

```yaml
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/pm_engine/dispatch/repair_lane.py
  kind: modify
- path: core/verify_contract.py
  kind: modify
- path: core/pm_engine/verification/serving.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_verify_dispatch_single_flight.py
  kind: new
```

## 1. verify 车道同 spec 单飞

- [ ] 1.1 core/pm_engine/dispatch/queue.py：新增 verify 车道在飞集合（:70-97，仿 _active_reviews/_active_parallel_plans，键=spec_name）；_enqueue（:196-213）与 _enqueue_front（:227-256）去重扩展为「未派发队列∪在飞」双查；派发成功登记（:930-937）、收工/异常回滚（:937-950）摘除；拒绝路径结构化留痕（:978 打印点同步）。
- [ ] 1.2 core/admin_monitor.py：复位直通道「verifier 入队重验」（:4816-4894）确认走同一守卫；存在旁路入队则在入口补查，拒绝时留痕并可由处置显式放行。
- [ ] 1.3 core/pm_engine/dispatch/repair_lane.py：repair 链成功/异常尾段入队（:620/:679）确认走同一守卫，命中在飞记拒绝留痕。

## 2. prepare 并发护栏

- [ ] 2.1 core/verify_contract.py：run_prepare_steps（:965-1041）增并发护栏——优先 per-run 隔离构建目录；不可行处对主树路径 prepare 加 fcntl 主机锁（复用 full-suite.lock 形态，带超时与 pid 记录）。
- [ ] 2.2 core/pm_engine/verification/serving.py：主树 prepare 调用点（:926 纯 cli、:989 web/api）接入 2.1 护栏。

## 3. 退避预算自适应与降级分流

- [ ] 3.1 core/agent_runner/runner.py：_create_worktree_with_backoff（:3388-3455）在固定序列（:3386）外按锁龄（lifecycle.py has_active_lock/_lock_since）自适应延长或提前放弃，预算配置化封顶；放弃保持 gave up 通道与文案（:3336）。
- [ ] 3.2 core/pm_engine/engine.py：_run_verification_pipeline 降级分支（:2563-2597）按异常分类——worktree 竞争类先重入新流程一次（重试前查在飞集合），仍败才 _run_legacy_verification；非竞争类维持直接降级；降级计数（:200）与告警（:2583）留痕保留。

## 4. 测试

- [ ] 4.1 tests/test_verify_dispatch_single_flight.py（新建）：同 spec 双路入队拒绝＋留痕（事件/repair 尾段/admin 直通道三例）；在飞收工后再入队放行；并发 prepare 护栏（锁串行化或隔离目录不互踩）；锁龄自适应退避（长锁不 210s 定额耗尽、超封顶快速放弃）；竞争类异常先重试新流程一次再降级、非竞争类直接降级。
- [ ] 4.2 运行既有 worktree backoff、conflict-recovery、verify contract 相关用例确认零回退。