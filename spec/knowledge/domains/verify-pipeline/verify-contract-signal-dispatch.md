# 验证契约信号语义二分
<!-- knowledge: capability=verify-contract-signal-dispatch rev=1 sources=spec/archive/2026-09-15-fix-verify-contract-signal-semantics -->

verify.yaml 起草信号按场景二分的派发契约：`missing` 只代表真缺失，覆盖重起草走专用 `redraft` 信号，消费端按类型区分处置指引。

## 现行规则

- 信号类型二分：`POST /api/verify-yaml-autodraft` 在契约可解析（`load_verify_contract` 非 None）且请求携带覆盖确认（overwrite=true）时派发 `verify_contract_redraft` 信号；`verify_contract_missing` 仅用于契约文件缺失或解析失败场景，不被覆盖确认旁路。两类型的响应均为 dispatched。
- redraft 信号载荷：severity=major、`source=ui-manual`、overwrite 标记与项目名 evidence 语义与 missing 信号一致。
- 有效契约无覆盖确认仍跳过：响应 skipped，不写任何信号。
- admin_monitor 消费端注册：SIGNAL_SEVERITY 将 redraft 映射为 major；SIGNAL_RECOMMENDATION 提供区别于 missing 的处置指引——先复核现有契约有效性，有效契约按权限边界默认不碰，用户已显式授权覆盖时方可重起草，重起草草稿同样须经 `bin/fenix_verify_contract.py` 三段自证全通后才落位；STORED_SIGNAL_TYPES 收录该类型；`_detect_family_explosion` 的 spec 空值项目名提取分支同时覆盖 redraft 类型。
- 消费唤起：未 escalated 的 redraft 信号被 admin_monitor 巡检拾取，按 evidence 提取项目名唤起 Administrator，使用 redraft 专用指引而非 missing 的纯起草指引。

## 溯源

- 2026-09-15 fix-verify-contract-signal-semantics — 将「覆盖重起草」语义从 missing 信号中拆出为 redraft 专用信号并补消费端注册与专用指引（此前信号双载两种语义，契约有效时发出的 missing 信号为假信号，实测烧 3 个 admin 自证 run）
