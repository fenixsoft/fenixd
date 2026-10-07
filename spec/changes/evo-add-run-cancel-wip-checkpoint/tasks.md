## Deliverables

```yaml
- path: core/wip_checkpoint.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/QualityTab.tsx
  kind: modify
- path: tests/test_impl_wip_checkpoint.py
  kind: modify
- path: tests/test_run_cancel.py
  kind: modify
```

## 1. 取消路径现场保全

- [x] 1.1 core/wip_checkpoint.py：锚点常量区新增 ANCHOR_CANCEL（"cancel"），沿用既有锚点体系
- [x] 1.2 core/agent_runner/runner.py：取消旗标命中确认处调用既有 `_wip_checkpoint_on_forced_kill(spec_name, cwd, anchor=ANCHOR_CANCEL)` 补 WIP checkpoint——时序：terminate/grace/kill 序列完成后、构造 cancel_error 与 break 前；助手自带 exclude_main_tree=True 主树车道跳过，MUST NOT 直连 _wip_checkpoint_commit_safe 裸调（默认不排除主树）。失败仅 WARNING 降级、绝不阻断取消收口；attempt 间隙（无 worktree）跳过；RunCancelledError 收口分支兜底（wt_path 可得则补一次，同排除主树）
- [x] 1.3 core/agent_runner/runner.py：修正取消审计告警 recommended_action 文案——仅替换「注意：取消路径不做 WIP checkpoint…将随 cleanup(success=False) 丢弃…」失实句（旗标登记/收口描述句保留），新文案如实描述：取消收口前已尽力 WIP checkpoint（未提交改动进入 attempt 分支 wip 提交可恢复；无 worktree 载体或主树车道无保全）、worktree 目录去向按车道（fast-track/transient 等登记复用遗产保留宽限期后回收，其余车道维持既有收口处置、分支与 wip 提交不受影响）。不得使用「失败 implementer worktree 将登记为 legacy 保留」表述（implementer 取消终态无 legacy 登记分支，实测不符）

## 2. dashboard 取消确认

- [x] 2.1 core/dashboard/static/src/pages/projects/components/QualityTab.tsx：「取消」按钮补确认弹窗（danger 标识，复用同文件 Modal.confirm 既有先例），确认后才调 cancelRun；错误处理沿用 ApiError.code 稳定错误码分支

## 3. 测试

- [x] 3.1 tests/test_impl_wip_checkpoint.py：覆盖取消锚点 checkpoint 写入、失败 WARNING 降级不阻断取消收口、attempt 间隙跳过、主树车道跳过（exclude_main_tree）
- [x] 3.2 tests/test_run_cancel.py：覆盖取消收口前已产 checkpoint 的集成用例与取消审计文案断言