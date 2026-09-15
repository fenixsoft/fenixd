# admin-dispatch-failure — 派发失败专用升级信号

## 场景：Administrator 派发期编程错误

- 前置：_invoke_administrator 抛编程类异常（提示词构造/序列化/参数错误等）。
- 行为：落 kind=escalation、signal_type=admin_dispatch_programming_error、severity=critical 记录，evidence 含异常类型/消息、core/ 内最深调用点（文件:行 函数名，traceback 提取）、原信号 signal_type/spec/severity；不再沿用原信号类型（可归类统计）。
- 重试：升级记录（编程错误与原类型两条路径）带 next_retry_at（now + escalation_cooldown_minutes）与 retry_count=0；巡检发现到期且记录未处置 → 直接调 _invoke_administrator 重试一次原信号（绕过 _handle_signal 节流、frozen spec 跳过、manual 派发不重试）；仍失败 → bump 既有记录 retry_count（上限 1），不追加新记录；重试或后续派发成功 → 该 spec 的派发失败升级记录标记 handled（resolve_note=「后续派发成功」）。

## 场景：编程错误 vs 运维失败

- 编程错误（TypeError/AttributeError/NameError/ValueError）→ admin_dispatch_programming_error（critical）。ValueError 子类（JSONDecodeError/UnicodeDecodeError 等数据类异常）会被归为编程错误——保守可见方向，evidence 保留完整异常消息供甄别。
- 运维失败（OSError/超时/provider 类）→ 保持原信号升级记录，不归类为编程错误。

## 场景：序列化防回退

- admin 提示词注入字段统一走 _str_field（dict/list → JSON 串）；单测防回退（evidence dict → 不抛 replace 错误、提示词正常构建）。

## 非目标

- 不改 run 失败分类熔断（run-failure-classification-circuitbreaker）。
- 不改基线 reset/孤儿检测机制。
- 不扩 alert_lifecycle._SIGNAL_CONDITIONS 闭环枚举：派发失败升级记录的闭环发生在 dispatch 时刻（后续派发成功即标记 handled），不经 lifecycle 扫描。