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

- [ ] 1.1 core/pm_engine/dispatch/queue.py：新增 verify 车道在飞集合（:70-97，仿 _active_reviews/_active_parallel_plans，键=spec_name）；_enqueue（:196-213）与 _enqueue_front（:227-256）去重扩展为「未派发队列∪在飞」双查；出队分流锁内原子「查在飞→命中即拒绝留痕并丢弃条目→未命中即登记」（在飞登记 MUST 与出队同 _queue_lock 锁段、对齐 _active_reviews 出队置位与 _reviews_dispatching 过渡窗口先例 queue.py:77-97，MUST NOT 延后到线程启动后的「派发成功」点 :930-937——本案第一路 13ms 即被 pop，登记晚于出队则「已出队未登记」窗口内第二路入队双查落空）；收工/异常回滚（:937-950）摘除；拒绝路径结构化留痕（:978 打印点同步）。
- [ ] 1.2 core/admin_monitor.py：复位直通道「verifier 入队重验」（:4816-4894）确认走同一守卫——已实测该通道经 handle_event("spec_implemented")（admin_monitor.py:4886-4889）汇聚到 _on_spec_implemented → _enqueue（engine.py:1478），守卫落在 _enqueue/_enqueue_front/出队分流即天然覆盖；若实现引入旁路入队则在入口补查，拒绝时留痕并可由处置显式放行。
- [ ] 1.3 core/pm_engine/dispatch/repair_lane.py：repair 链成功/异常尾段入队（:620/:679）确认走同一守卫，命中在飞记拒绝留痕。

## 2. prepare 并发护栏

- [ ] 2.1 core/verify_contract.py：run_prepare_steps（:965-1041）增并发护栏——优先 per-run 隔离构建目录；不可行处对主树路径 prepare 加 fcntl 主机锁（复用 full-suite.lock 形态，带超时与 pid 记录）。护栏 MUST 落在 run_prepare_steps 函数内按调用 cwd 判定主树路径：主树调用方共三处（serving.py:926/:989、validate_contract verify_contract.py:746——契约校验入口同样对主树跑 prepare），worktree 调用（serving.py:152）不涉及。
- [ ] 2.2 core/pm_engine/verification/serving.py：主树 prepare 调用点（:926 纯 cli、:989 web/api）接入 2.1 护栏。

## 3. 退避预算自适应与降级分流

- [ ] 3.1 core/agent_runner/runner.py：_create_worktree_with_backoff（:3388-3455）在固定序列（:3386）外按锁龄（lifecycle.py has_active_lock/_lock_since）自适应延长或提前放弃，预算配置化封顶；放弃保持 gave up 通道与文案（:3336）。
- [ ] 3.2 core/pm_engine/engine.py：_run_verification_pipeline 降级分支（:2563-2597）按异常分类——worktree 竞争类先重入新流程一次（重试前校验 worktree 锁已释放：lifecycle.has_active_lock/_lock_since——派发在飞集合对同 spec 自指，自身条目必然在飞，无 peer 判别力），仍败才 _run_legacy_verification；非竞争类维持直接降级；降级计数（:200）与告警（:2583）留痕保留。

## 4. 测试

- [ ] 4.1 tests/test_verify_dispatch_single_flight.py（新建）：同 spec 双路入队拒绝＋留痕（事件/repair 尾段/admin 直通道三例）；在飞收工后再入队放行；并发 prepare 护栏（锁串行化或隔离目录不互踩）；锁龄自适应退避（长锁不 210s 定额耗尽、超封顶快速放弃）；竞争类异常先重试新流程一次再降级、非竞争类直接降级。
- [ ] 4.2 运行既有 worktree backoff、conflict-recovery、verify contract 相关用例确认零回退。