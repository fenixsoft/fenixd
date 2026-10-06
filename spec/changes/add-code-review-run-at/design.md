## Context

`core/admin_monitor.py` 的 `_run_code_review_checkpoint`（≈:1479）与 `_run_regression_checkpoint`（≈:2111）触发判定均直接比较 `sr_cfg["run_at"]`（`get_self_review_config` 段），`admin.code_review` 配置段自身无 run_at——周期审查与自省（连带其分析链）恒同刻齐发。2026-10-06 05:50 该叠峰在账户级打出 provider 429（错误码 1302），spec-review 0-rounds 连败 5 次熔断。`ConfigLoader.get_code_review_config`（core/config.py:2090）已是 code_review 段的单源读取器（enabled/max_files/scope/stall_alert_minutes 均在此兜底），新增 run_at 的自然落点。

窗口侧：`core/code_review.py:compute_window` 现读 `.fenix/self_review_state.json` 的 `last_run_at` 作 `window_start`；`code_review_state.json` 现仅存 `last_run_date`（自然日防重用），无时刻水位。

## Goals / Non-Goals

- Goals：code-review 触发时点可独立配置；缺省逐位等于现状；解耦后窗口覆盖无缺口。
- Non-Goals：不改回归车道（同槽位事实另行立项）；不改 CLI 重试参数与 429 退避（既有 add-code-review-concurrency-and-429-resilience 域）；不改手动触发路径；不引入 cron/绝对时刻表（仍挂巡检节拍）。

## Decisions

### D1 独立键缺省回退自省（用户定调：暂不挪时点）

`get_code_review_config` 新增 `run_at`：cr 段存在且能被既有 `_parse_run_at` 口径解析为合法 HH:MM 才生效；其余一切（键缺失/非法字面量/非字符串类型）回退 `get_self_review_config(config)["run_at"]`。缺省路径零行为变化；用户后续在 Dashboard 改值即错峰。

### D2 窗口水位归审查车道自身（解耦的必要配套）

若只挪触发时点、窗口仍读自省水位：审查时点晚于自省时（如 13:00 vs 01:00），`window_start` 被当晨自省覆写为当日 01:00，昨夜「前次审查→当晨自省」段的变更滑出所有窗口——静默覆盖缺口。故：

- 调度收尾在 `code_review_state.json` 写 `last_run_at`（本轮审查完成时刻，aware ISO8601 本地时区表述，与 `self_review_state.last_run_at` 一致；保留 `last_run_date`）。
- `compute_window` 优先读 `code_review_state.last_run_at`；缺失（首跑/存量）回退自省 `last_run_at`，再缺失回退 `now - 24h`。`window_kind` 二值映射不变（读到任一水位→`"last_run"`，双缺失→`"fallback"`），消费方日志/审计口径不受三态水位影响。
- 存量部署首轮回退自省＝现状逐位一致；自第二轮起窗口跟审查自身节奏，语义严格更正确（「审上次审查之后的变化」）。

### D3 检查点时序约束保留

code-review 检查点 MUST 仍先于自省检查点（自省收尾覆写自身 `last_run_at` 会退化窗口）。该约束针对同轮巡检内的执行顺序，与触发时点（自然日阈值）解耦正交：时点错开后两检查点在不同巡检轮各自判定，同轮相遇时顺序约束仍兜底。

### D4 脏值回退对齐 scope 口径

一切非法 run_at 回退缺省，巡检 MUST NOT 因配置脏值中断（对齐 scope 白名单回退的既有设计）。

## Risks / Trade-offs

- ［低］两车道时点被用户设为不同值后，窗口从「自省节奏」切到「审查节奏」——首轮回退过渡由 D2 覆盖；审查停摆数日时窗口随其水位拉长，与「窗口=距上次审查」语义一致。
- ［低］Dashboard 新增时间输入需 HH:MM 校验；脏值由 D4 后端兜底，前端仅体验层拦截。
- ［记录］回归车道仍与自省同槽位，叠峰削掉两分之一；后续同法立项即可复用本变更模式。

## Migration Plan

纯增量配置键＋状态字段新增，无迁移：存量 `code_review_state.json` 缺 `last_run_at` 走回退路径；配置未加键走自省回退。上线即兼容。

## Open Questions

（无——时点值用户已定调「保持 01:00，仅解耦」；回退与窗口语义见 D1/D2。）
