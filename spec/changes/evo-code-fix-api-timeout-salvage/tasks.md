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

- [ ] 2.1 core/code_fix.py：_run_batch_created（:3170）失败分支命中 api_timeout 且工作区脏时，先复用 _salvage_commit（:1711）把 WIP 提交到批分支，再照常 _safe_cleanup（调用点 :3195；cleanup success=False 对非 verify- 前缀分支自动登记 recovery legacy，lifecycle.py:521-531；MUST NOT 跳过 cleanup——漏掉则 spec 锁滞留，下一批 create() 恒 None 车道死锁，见 code_fix.py:3148-3150 既有警告），并对 "code-review-fix" 调 mark_legacy_reusable（legacy_registry.py:103）置 reuse 标记；_salvage_commit 返回 False 时按现状失败收尾（fail-open，不改变跳批推进）；工作区干净则跳过 salvage 与 reuse 标记按现状清理
- [ ] 2.2 core/code_fix.py：同链下一批接续走 create 既有认领通路——上一批已 mark_legacy_reusable 后，_run_batch_inner 的 wm.create（约 :3134）经 _take_reusable_worktree（lifecycle.py:166）自动认领 salvaged 分支，salvaged 提交对重试批可见；认领不可用时 create 既有 fail-open 回退全新建树。本任务 MUST NOT 在建树前调用 consume_legacy（回收端：出册 + worktree remove + branch -D，legacy_registry.py:79-97/392-399，会删除 salvaged 提交载体）；若现有认领链路即满足接续，本任务收敛为「验证认领链路 + 补测试」（3.2），不新增消费端代码
- [ ] 2.3 非 api_timeout 失败保持原行为（立即清理 + 跳批推进），日志仍带结构化签名便于追溯

## 3. 测试

- [ ] 3.1 tests/test_code_fix_api_timeout_salvage.py：api_timeout 签名判别用例——terminal_reason=="api_error" 与 synthetic "Request timed out" 两形态命中、确定性失败不误标
- [ ] 3.2 tests/test_code_fix_api_timeout_salvage.py：salvage 链路用例——失败分支 salvage commit 落批分支、legacy 登记 + mark_legacy_reusable 置 reuse、下一批 wm.create 经 _take_reusable_worktree 认领继承 salvaged 分支、认领不可用时 fail-open 全新建树；仿 tests/test_code_fix_salvage.py 的夹具风格