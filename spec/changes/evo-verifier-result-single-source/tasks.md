# 任务

## Deliverables

```yaml
- path: core/pm_engine/verification.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_verdict_contamination.py
  kind: new
```

## 1. 统一裁决读取入口 _read_verdict(spec_name)

- [ ] 1.1 core/pm_engine/verification.py：verify-progress 优先 + 主树共享 role/spec 戳双校验回退 + unreadable 语义；legacy 与 planner 两路径全部改走入口，删除各自读取分支。
- [ ] 1.2 消除 _verifier_result_is_stale 的 run_id fail-open（verification.py:2528-2530）：role≠verifier 或缺 role 的主树共享文件一律不采信，不依赖 run_id 能否解析出 epoch。

## 2. 主树共享文件写入 role/spec 戳隔离

- [ ] 2.1 core/agent_runner/runner.py：_execute_agent 拷回 worktree 根 .fenix-run-result.json 到主树共享文件时（runner.py:2677-2686），按 agent_type 注入 role（implementer|verifier|planner|judge|repair）与 spec 戳；无 role 视为旧格式遗留。
- [ ] 2.2 core/pm_engine/verification.py：裁决读路径对主树共享文件丢弃 role≠verifier/缺 role 者。该丢弃仅限裁决读路径，不得改变 _read_implementer_result、_read_planner_result 主树回退与 family._read_prev_impl_conclusions 的既有采信行为。

## 3. implementer 残留污染回归测试

- [ ] 3.1 tests/test_verdict_contamination.py：模拟主树共享文件被 implementer 残留 status=success 污染（role=implementer 或缺 role，且 run_id 不匹配 `-\d{10,}-a\d+$`，即当前会误判 blocked 的红灯场景），断言 legacy/planner 两路径均不将其当裁决，unknown-status 走 stale/foreign 护栏 re-dispatch。
- [ ] 3.2 同测试补机械锚点：断言 legacy 与 planner 两处裁决读取确实调用统一入口 _read_verdict（防「测试预先已全绿、改动实为空跑」的零变更洗白）。
