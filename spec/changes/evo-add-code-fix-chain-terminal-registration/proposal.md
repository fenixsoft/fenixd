## 背景

code-review 台账自动修复链（code-fix 链）在自动修复总开关被关闭时以 disabled 终态收口：core/code_fix.py checkpoint() 的 disabled 分支只写 fix-progress.json（phase=blocked、reason=disabled），不落任何告警或待办登记。同文件其他终态路径均有登记面——失败预算耗尽走 _write_retry_exhausted_alert 与 _append_todo_entry（code_fix.py:886-895），零进度护栏走 AdminStore 告警（code_fix.py:6136 起）——唯独 disabled 终态完全静默。

2026-11-22T08:44Z 总开关关闭后链悬置超 31 小时：747 条存量审查发现中 561 条（75.1%）无修复出口，修复进度台账零变化，感知通道只剩每日自省回源与用户主动打开 dashboard 面板（唯二被动展示端点 core/dashboard/routes/code_review_routes.py:304 与 core/dashboard/data/code_review.py:155）。admin_alerts.json 现存 150 条告警中 fix-disabled 相关为零，todo.md 活跃待办亦无该链登记。

## 目标

disabled 终态收口时在 admin 告警与 todo 待办两面留登记，内容含终态原因、剩余未修复条数（total-done）与重新触发入口提示；同一 disabled 期去重只登记一次；人工重新触发后链再次 disabled 时能落新登记。

## 非目标

- 不改变自动修复总开关语义，不自动重开链——重新触发仍是人工决策，dashboard POST /api/code-review/fix-run 入口现成（override_enabled 临时授权跳过总开关，其余守卫原样）。
- 不处理 disabled 以外的终态（失败预算耗尽、零进度护栏已有各自登记面）。
- 不动审查发现台账本体与修复批次逻辑。