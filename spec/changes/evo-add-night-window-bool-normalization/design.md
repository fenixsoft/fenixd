## Context
- 解析单源：core/code_fix.py _night_quiet_window_disabled :3350-3353（仅认空串/off）、_parse_night_quiet_windows :3367-3395（split('-')，非法返回 None）。
- 三消费点：code-fix 车道 :3970 起、admin_monitor.py _code_review_night_window_defer :2015/2056、_night_dispatch_block_reasons :6258/6299-6302，均 `if not windows` 静默。
- 既有模式：消费期 WARNING code_fix.py:3931-3939（同值单实例一次）；载入期 lint 参照 core/config.py _maybe_warn_deprecated_stuck_keys :3002；每日提醒可复用 _write_night_quiet_window_alert 通道。
- 已落地面：归档 evo-add-night-window-inflight-guard 的 predicted-crossing 顺延与 admin 避让复用同一单源，语义改动自动生效。

## Goals / Non-Goals
- Goals：布尔/非法值语义确定化；载入期+消费点告警对等；停用态可感知。
- Non-Goals：不改窗值语法本身；不改顺延/salvage 机制；不代做运维配置修改。

## Design
- 同义化判定作用于原始值（str 化之前）：_night_quiet_window_disabled（:3350）入口先判 isinstance(bool)——False 等价 off、True 记非法——再落既有字符串判定；_parse_night_quiet_windows（:3367）MUST 在其 :3380 `text = str(raw).strip()` 之前同判原始 bool，否则 False 已被 str 化为 "False"、经该函数的路径同义化静默失效。两解析函数保持「纯解析不告警」既有契约（code_fix.py:3378 docstring），载入期 lint 只挂 config.py（下一款），MUST NOT 下沉进解析单源——admin_monitor 两消费点（:2059/:6314）共用它，下沉即引入重复告警源。
- 载入期 lint 挂 config.py 既有弃用键检查同点，进程级去重。
- 审查/admin 两处 `if not windows` 前补解析失败告警（复用 :3931-3939 文案与去重集）。
- 每日提醒按（窗值,自然日）节流。

## Risks / Trade-offs
- 同义化会消除现有消费期 WARNING（False 不再走解析失败路径）——载入期 lint 接棒保证可视性不降。
- 布尔 true 拒判为非法而非「全天停派」——语义更保守，避免误停派。