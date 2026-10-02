<!-- knowledge: capability=admin-dispatch-failure rev=1 sources=spec/archive/2026-09-21-evo-admin-dispatch-failure-escalation -->

# 管理员派发失败升级

Administrator 派发期失败的专用升级信号、编程错误/运维失败分层与受限自动重试。

## 现行规则

- `_invoke_administrator` 抛编程类异常（提示词构造/序列化/参数错误）时，落 `kind=escalation`、`signal_type=admin_dispatch_programming_error`、`severity=critical` 的升级记录，不沿用原信号类型（可归类统计）；evidence 含异常类型/消息、`core/` 内最深调用点（文件:行 函数名，traceback 提取）、原信号的 signal_type/spec/severity。
- 分层边界：`TypeError`/`AttributeError`/`NameError`/`ValueError` 归编程错误（`ValueError` 子类如 `JSONDecodeError`/`UnicodeDecodeError` 等数据类异常保守归入编程错误，evidence 保留完整异常消息供甄别）；`OSError`/超时/provider 类属运维失败，保持原信号升级记录，不归编程错误。
- 派发失败升级记录（编程错误与原类型两条路径）携带 `next_retry_at`（now + escalation_cooldown_minutes）与 `retry_count=0`；巡检发现到期且记录未处置时，直接调 `_invoke_administrator` 重试一次原信号（绕过 `_handle_signal` 节流；frozen spec 跳过；manual 派发不重试）。
- 重试仍失败则 bump 既有记录的 `retry_count`（上限 1），不追加新记录、不无限重试；重试或后续派发成功时，该 spec 的派发失败升级记录标记 handled（resolve_note=「后续派发成功」）。
- admin 提示词注入字段统一走 `_str_field`（dict/list 序列化为 JSON 串），防对 dict 调 `str.replace` 类崩溃；有防回退单测钉住。
- 派发失败升级记录的闭环发生在 dispatch 时刻（后续派发成功即标记 handled），不纳入 alert lifecycle 闭环扫描枚举。

## 溯源

- 2026-09-21 evo-admin-dispatch-failure-escalation（spec/archive/2026-09-21-evo-admin-dispatch-failure-escalation） — 建立派发失败专用信号 admin_dispatch_programming_error、编程/运维异常分层、单次冷却重试与 _str_field 序列化防回退
