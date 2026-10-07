# add-run-cancel-wip-checkpoint

## Why

2026-10-07 用户经 dashboard 取消 run code-fix-1791375870（告警 13377b6e2004）暴露：run 取消终止路径直接以 success=False 收口，不做 WIP checkpoint（core/agent_runner/runner.py RunCancelledError 分支），与 freeze（ANCHOR_FREEZE_HOLD）、turn-limit 强杀、extension-tail、瞬态退避路径均有现场保全的设计不一致。本次因 run 刚启动无损失，若取消撞上夜间在飞重批，整段未提交现场将无法收回。另发现：QualityTab 的「取消」按钮无任何确认直接发取消请求；取消审计告警文案「未提交工作将随 cleanup(success=False) 丢弃」与 worktree_manager 的 register_legacy 保留语义不符，会误导人工判断。

## What Changes

- run 取消路径补 WIP checkpoint：取消旗标在轮询环内被确认命中（worktree 在手）时，先经既有 _wip_checkpoint_commit_safe 以新锚点 cancel 保全现场，失败仅 WARNING 降级、绝不阻断取消收口；attempt 间隙（无 worktree）跳过；RunCancelledError 收口分支兜底。
- QualityTab「取消」按钮补确认弹窗（danger 标识），确认后才调用取消 API。
- 修正取消审计告警 recommended_action 文案，如实描述 legacy 保留语义。

## Impact

- Affected specs: run-cancel-site-preservation（取消路径现场保全为新增能力面）
- Affected code:
  - core/wip_checkpoint.py：锚点常量区新增 ANCHOR_CANCEL
  - core/agent_runner/runner.py：取消旗标命中确认处与 RunCancelledError 收口分支接入 checkpoint；取消审计文案修正
  - core/dashboard/static/src/pages/projects/components/QualityTab.tsx：取消按钮补确认
- Tests:
  - tests/test_impl_wip_checkpoint.py、tests/test_run_cancel.py 扩展
- 风险：低——复用既有 checkpoint 内核与锚点体系，不改变取消语义本身；checkpoint 失败按既有惯例 WARNING 降级。