# add-impl-terminal-nocommit-gate tasks

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/worktree_manager.py
  kind: modify
- path: tests/test_terminal_nocommit_gate.py
  kind: new
```

## 1. 终态零提交门（TDD）

- [x] 1.1 写失败测试：implementer 成功收口、分支零提交且 wt_dirty 非空 → cleanup 被调用前抛 `AgentArtifactGateError`，error 含 `[terminal-no-commit]` 前缀与归因文案；分支有新提交、或零提交且 worktree 干净、或 agent_type 为 fast-track/repair/verifier 时均不拦截（判定矩阵全分支）
- [x] 1.2 写失败测试：门触发后进入既有 except 通道——锚点 B WIP 提交（`_wip_checkpoint_before_backoff` / `commit_wip_checkpoint` 被调用）发生、退避后续做复用同一 worktree 且带 `--resume`；耗尽后 error 带 `[provider-transient]` 前缀、worktree keep_for_reuse
- [x] 1.3 实现 runner.py 成功收口路径的门判定（wt_dirty 取证后、cleanup/分流前）：`agent_type == "implementer"` 且 `rev-list --count main..branch` == 0 且 wt_dirty 非空 → 抛 `AgentArtifactGateError`；rev-list 失败 fail-open 不拦；确认 except 通道内 `record_transient_break` 尽量跳过（D1），否则注释声明「多计保守」
- [x] 1.4 跑通 1.1/1.2 全部测试

## 2. 机械归因（TDD）

- [x] 2.1 写失败测试：归因函数读 run 转录末轮 assistant text——XML `<function_calls>` 形态 → 「格式回退截断」；markdown fenced code 工具调用形态 → 「格式回退截断」；无特征 → 「未提交即收工」；用 1789001677 转录末轮 text 真实样本做 fixture 回归锚
- [x] 2.2 实现归因正则函数（runner.py 内或独立小模块），接入 1.3 的 error 文案组装；纯文本匹配零 LLM、转录缺失时降级为「未提交即收工」
- [x] 2.3 跑通 2.1 全部测试

## 3. cleanup rmtree 前留档（TDD）

- [x] 3.1 写失败测试：cleanup 的 `git worktree remove` 失败转 rmtree 且 worktree dirty → `git stash create` 被调用且返回 SHA 记入日志；stash create 失败/超时 → 仅 WARNING、清理照常
- [x] 3.2 实现 worktree_manager.py rmtree fallback 前的 stash create 留档（全 agent_type 生效、失败降级不阻断）
- [x] 3.3 跑通 3.1 全部测试

## 4. 回归与收口

- [x] 4.1 全量既有回归：tests/test_agent_runner.py、tests/test_impl_wip_checkpoint.py、tests/test_worktree_manager*.py（如存在）、tests/test_pm_verification.py 中零变更哨/交付物守卫相关用例零回归
- [x] 4.2 自检：grep 确认门判定仅 implementer 车道生效、fast-track/repair 成功不清理路径未被波及、`record_transient_break` 调用点语义与 D1 处置一致
