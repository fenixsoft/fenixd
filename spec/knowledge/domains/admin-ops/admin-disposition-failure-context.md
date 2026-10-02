<!-- knowledge: capability=admin-disposition-failure-context rev=1 sources=spec/archive/2026-09-10-fix-admin-disposition-empty-shell -->

# 处置失败记录自解释

Administrator 处置 run 异常结束时，final disposition 记录必须自带失败原因与信号上下文，无需日志考古。

## 现行规则

- 处置 run 异常结束（`_run_claude` 抛出异常、CLI 非零退出、结果实例文件缺失）时，daemon 落盘的 final disposition 记录满足：`result="failed"`、`error` 字段非空且等于异常文本（含退出码或错误标识）、`recommended_action` 兜底为触发信号的 `recommended_action`（非空）、`description` 兜底 `disp.problem or signal.description`；`summary` 与 `action_taken` 允许为空。空壳记录（summary 与 action_taken 均空且无 error）不存在。
- 处置成功（实例文件写出且 result 非 failed）时，final 记录各字段取自实例文件内容，`error` 为空字符串或不出现。
- `run_administrator` 的 `_run_claude` 异常路径记一条 WARNING 日志（component=agent_runner，含 run_id 与异常文本），失败可在 `fenixd.log` 直接检索，不静默。
- 运维记录页 disposition 卡片在记录携带非空 `error` 时展示失败原因；`summary` 为空的失败记录显示 error 文本而非「（无叙述总结）」占位文案。
- 数据兼容：`admin_alerts.json` 的 `error` 为可选键，读侧对无该键的存量记录兼容，渲染不报错。

## 溯源

- 2026-09-10 fix-admin-disposition-empty-shell（spec/archive/2026-09-10-fix-admin-disposition-empty-shell） — 消灭失败处置空壳记录：error 字段、recommended_action/description 兜底、失败 WARNING 日志与 UI 展示
