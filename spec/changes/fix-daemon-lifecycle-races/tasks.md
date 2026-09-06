## Deliverables

```yaml
- path: core/state_machine.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: bin/fenixd_supervisor.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/TokenBudgetPanel.tsx
  kind: modify
```

## 1. 状态机幂等与重验计数

- [ ] 1.1 `transition()`/`transition_gate()` 增加幂等自迁移短路：`new_status == old_status` 时打 INFO 日志并返回 True，不进 VALID_TRANSITIONS 拒绝分支；全库 grep `transition(`/`transition_gate(` 调用点，对依赖返回 False 阻断重复副作用的点（如 engine.py:332 total_duration 覆盖防护）改为前置状态判断或在 findings 登记幂等覆盖无害的依据
- [ ] 1.2 STATE.md 新增内部字段 `_verify_redo_count`（加入 state_machine.py 字段名单，与 `_impl_run_budget_used` 同段）；`recover_interrupted` 的 testing→implemented 分支递增该计数并持久化；实现运行中断不递增、仅重启恢复递增
- [ ] 1.3 重验超限冻结：恢复路径检查 `_verify_redo_count` 达 `agents.verify_redo_budget`（ConfigLoader.get，缺省 3）时调用 `freeze_spec`（error 注明「重启重验超限，等待人工裁决」）且本次启动不再派发 verifier；verify 自然通过（verified/done 落定处，对齐 `_verify_fail_rounds` 清零点）清零计数；`unfreeze_spec` 解冻时清零

## 2. 启动终态补写扫描

- [ ] 2.1 `liveness.py` 实现 terminal-state sweep：扫 `.fenix/runs/*.jsonl`，尾部无终态事件（result/interrupted/error/cancelled，口径对齐 `runner.py:2595` `_run_was_interrupted` 与 `admin_monitor.py:855`）的 run 追加 `{"type": "interrupted", "reason": "startup terminal-state sweep"}`；补写不检查遗留进程存活；仅启动期执行一次，运行期不重复
- [ ] 2.2 `fenixd.py` 启动时序接入 sweep：AgentRunner 初始化后、任何派发与恢复派发之前执行；sweep 异常不阻塞 daemon 启动（WARNING 降级）

## 3. supervisor 自报与一致性自检

- [ ] 3.1 `bin/fenixd_supervisor.py` `main()` 启动时原子覆写 `.fenix/supervisor_runtime.json`：`{"sigkill_wait": <n>, "started_at": <iso>}`（n = `_sigkill_wait_seconds()` 计算值）
- [ ] 3.2 `fenixd.py` 启动自检：`shutdown_drain_seconds > 0` 时读取 runtime 文件，缺失（旧代码 supervisor）/ `sigkill_wait < drain + 120` / `started_at` 漂移超阈值 → logger WARNING + `_append_project_log` 提示重启 supervisor；一致配置静默通过

## 4. push 单飞

- [ ] 4.1 `pm_engine` 实例级 `threading.Lock`；`approve_push` 全临界区（status 重读 → git push → transition(pushed)）持锁执行，锁内 status 非 done 幂等跳过返回 True；并发第二流排队后见 pushed 跳过，不再产生双 push / 重复 project log / pushed→pushed ERROR

## 5. stale-verdict 状态判据

- [ ] 5.1 verifier/planner-judge 结果处理入口增加状态判据：处理时 spec 状态非 testing → 结果 DEBUG 丢弃（日志注明 run_id 与当前状态），不执行迁移
- [ ] 5.2 定位并拆除被拒结果的 fallback 重派路径（02:13 事故的 `implemented→testing` 回退 + Dispatching verifier 重派），确保被拒结果零派发动作

## 6. 配置 UI 同步

- [ ] 6.1 `TokenBudgetPanel.tsx` 增加 `agents.verify_redo_budget` 配置项（对齐 impl_run_budget 的既有交互模式），保存后经现有配置热更新生效

## 7. 回归验证

- [ ] 7.1 单元测试：幂等自迁移 INFO+True（真实非法迁移仍 ERROR）/ 计数恢复递增与跨重启持久化 / 超限冻结与 unfreeze 清零 / sweep 补写（含孤儿进程存活场景）与正常运行不误伤 / push 单飞双并发仅一次 push / 状态判据丢弃旧结果且正常路径不受影响
- [ ] 7.2 全量测试套件回归 + 行为自检三层干跑，确认零新增失败
