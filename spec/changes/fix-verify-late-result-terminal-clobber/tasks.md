## Deliverables

```yaml
- path: core/pm_engine/verification/legacy.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/pm_engine/verification/judge_gate.py
  kind: modify
- path: tests/test_daemon_lifecycle_races.py
  kind: modify
- path: tests/test_verify_lane_terminal_reclaim.py
  kind: new
```

## 1. 迟到结果终态丢弃（D6 复核补齐）

- [ ] 1.1 `core/pm_engine/verification/legacy.py` foreign-role/foreign-stamp 分支（~L137-166）：在分支入口、`_verified_gate_refuses` 之前插入当前状态复核，非 `testing` 时 `logger.debug` 记录丢弃原因与当前状态并 return，不执行 `update_spec`、不触发 re-dispatch
- [ ] 1.2 `core/pm_engine/verification/legacy.py` unknown-status+stale 分支（~L171-196）：`_verifier_result_is_stale` 判 True 后、`update_spec` 之前插入同款复核，非 `testing` 时 DEBUG 丢弃并 return，且跳过 `_record_infra_failure`
- [ ] 1.3 `core/pm_engine/verification/legacy.py` 成功路径 stale 守卫分支（~L283-304）：同款复核，非 `testing` 时 DEBUG 丢弃并 return，跳过 `update_spec` 与 `_record_infra_failure`
- [ ] 1.4 回归确认 testing 状态下三分支行为不变：error 文案（"stale/foreign verifier result replayed — re-dispatching fresh verify"）、`tester_run=None`、`_record_infra_failure` 记账、重派语义逐项与现状一致（`tests/test_daemon_lifecycle_races.py` 既有用例全绿）
- [ ] 1.5 新增用例（`tests/test_daemon_lifecycle_races.py`）：构造 SPEC 处于 `pushed`/`implemented`/`done` 时迟到的 stale/foreign 结果 → 状态字段零变化、无 infra 记账、无 re-dispatch、DEBUG 日志含当前状态

## 2. verified 收敛点回收在飞 verify 车道

- [ ] 2.1 `core/pm_engine/engine.py` `_on_spec_verified`：新增 verify 车道收尾——`_remove_queued_entry(spec_name, "verifier")` 摘除在队条目 + `cancel_run(f"verify-{spec_name}", reason=..., by="verify-lane")` 请求取消在飞 run，照搬 `_stop_parallel_plan` 范式
- [ ] 2.2 收尾整体 try/except 兜底：异常记 WARNING（含 spec 与异常摘要），不向 verified 主流程（done → push 链）传播
- [ ] 2.3 收尾判断正确性：仅当 runner/dispatcher 可用时执行收尾（stub context 兼容），不越权取消其它 spec 或其它 agent_type 的 run
- [ ] 2.4 新增 `tests/test_verify_lane_terminal_reclaim.py`：在飞 verifier run 登记后 SPEC 达成 verified → `cancel_requested` 到达属主轮询环；在队 verifier 条目被摘除；runner 异常时 verified 流转不受影响；其它 spec 的 run 不被波及

## 3. 机械快道裁决来源戳

- [ ] 3.1 `core/pm_engine/verification/judge_gate.py` `_all_green_fast_path`：payload 补 `"role": "verifier"`（保留 `mechanical: true` 与既有字段），写回失败退化为常规 judge 的既有语义不变
- [ ] 3.2 新增用例：快道产物经 `_read_verdict`/`_read_verifier_result` 读取 role 校验通过、status 正常读取；`_verifier_result_is_stale` 对同 spec 新鲜快道文件不误判；跨 spec 戳（spec 不符）仍判不采信

## 4. 验证

- [ ] 4.1 全量回归：`tests/test_daemon_lifecycle_races.py`、`tests/test_verify_lane_terminal_reclaim.py` 及 verification 相关测试套零失败
