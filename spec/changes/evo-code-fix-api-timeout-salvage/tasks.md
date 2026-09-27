## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix_api_timeout_salvage.py
  kind: new
```

## 1. 终态签名结构化

- [ ] 1.1 core/agent_runner/runner.py：_run_claude 非 0 退出分支（约 :5047-5066）判别 api_timeout 签名（末次 result 事件 terminal_reason=="api_error" 或 result 文本含 "Request timed out"），把布尔标记挂到失败异常上，不改变既有异常消息文本
- [ ] 1.2 core/agent_runner/maintenance_runs.py：run_code_fix 失败分支透出结构化签名（api_timeout、exit_code、stderr 摘要）到失败记录与日志，替代仅 str(e) 压扁

## 2. 失败现场 salvage

- [ ] 2.1 core/code_fix.py：_run_batch_created（:3170）失败分支命中 api_timeout 且工作区脏时，不再直接 _safe_cleanup（:3519）：复用 _salvage_commit（:1711）把 WIP 提交到批分支，并登记 recovery legacy 保全现场；工作区干净则跳过 salvage 按现状清理
- [ ] 2.2 core/code_fix.py：同链下一批建树（_run_batch_inner 的 wm.create，约 :3134）前消费该 legacy（core/worktree_manager/legacy_registry.py 的 consume_legacy），使 salvaged 提交对重试批可见；无 legacy 或消费异常时 fail-open 降级为现状行为
- [ ] 2.3 非 api_timeout 失败保持原行为（立即清理 + 跳批推进），日志仍带结构化签名便于追溯

## 3. 测试

- [ ] 3.1 tests/test_code_fix_api_timeout_salvage.py：api_timeout 签名判别用例——terminal_reason=="api_error" 与 synthetic "Request timed out" 两形态命中、确定性失败不误标
- [ ] 3.2 tests/test_code_fix_api_timeout_salvage.py：salvage 链路用例——失败分支 salvage commit 落批分支、legacy 登记、下一批建树消费 legacy、消费异常 fail-open；仿 tests/test_code_fix_salvage.py 的夹具风格