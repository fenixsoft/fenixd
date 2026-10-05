# 全仓审查限流终局续跑与触发防叠加

<!-- knowledge: capability=repo-review-ratelimit-resume rev=1
     sources=spec/archive/2026-10-06-evo-add-code-review-ratelimit-resume -->

全仓审查 run 死于 429 限流后的自动续跑闭环：终局归因、手动/周期双车道统一重派消费、分片剃余续跑、全仓快照核销覆盖完整性门，以及上一轮未消化完时的手动全仓触发确认。

## 规则

- **429 终局归因双源**：审查 run 非零退出终局时，限流归因以降噪后异常文本的限流分类先行；未命中则回退 result 事件判定——runner 把 result 事件的 `api_error_status` 与 `result` 文本挂到终态异常，仍不足时兜底重读 run jsonl 最后一条 `type=result` 事件，`api_error_status` 解析为 429 或 result 文本命中限流签名即判限流终局。归因命中即登记 `ratelimit_redispatch` 意图、标注 run jsonl 并令 provider 进限流冷却；同 run_id 幂等只登记一次。降噪只作用于日志与 error 字段、不动 result 事件（见 [ADR-235](../../adr/ADR-235-cli-stderr-noise-single-source-triple-separation.md)）。
- **重派消费双车道统一**：手动审查 worker 与周期调度 worker 同源消费重派意图——各自把意图上交同一 admin_monitor 实例的共享排程入口，共享重派上限（`RATELIMIT_REDISPATCH_MAX=1`）与待发 Timer 句柄，手动+周期合计只重派一次，不叠加各耗额度；300 秒限流冷却（`PROVIDER_RATELIMIT_COOLDOWN_SECONDS`）延迟重投递、冷却到期前不重派、单飞让位（车道忙或已有外部 code-review run 在跑即放弃）都在共享入口内执行；放弃与非法意图（无合法 `cooldown_until_epoch`）不计配额或占额不退（防风暴优先）。admin_monitor 未装配（fallback 宿主）时意图记日志放弃并保持告警可见（run jsonl 已标注可取证），不静默丢弃。
- **分片剃余续跑**：重派前把 manifest 剃成「原清单 − 重派链累计已覆盖文件」——覆盖取原 run 及其 `redispatch_of` 重派链产物 `file` 字段并集，对原 manifest 求补（只删不改序），重派 run 只跑剩余文件并保留 `redispatch_of` 链路标注；剩余为空（原 run 已全覆盖，如死于收尾段）不重派；剃余失败回退原 manifest 全量重派。
- **快照核销覆盖完整性门**：`manual_full` 收尾的全仓快照核销仅在本轮累计覆盖 ⊇ 完整 manifest 时解锁执行——重派 run 以原 run 完整 manifest 为基准、跨 `redispatch_of` 链累计判定，普通 manual_full run 以本轮 manifest 对本轮产物累计判定。manifest 缺失/损坏/为空或守卫异常一律按未覆盖锁定（宁锁勿白洗），锁定时记 WARNING 维持抢救红线、不核销，等剩余文件重派补齐后由后续 run 解锁。守卫唯一实现在收尾核销分支，重派消费侧不重复判定。
- **二次全仓叠加防护**：手动 full 触发且未携带 `confirm=true`（严格布尔判定，非空字符串不放行）时，若台账 `open` 条数超过阈值（`admin.code_review.manual_full_open_warn`，缺省 30，显式 0 关闭守卫），POST 回 409 确认态（错误码 `code_review_open_backlog`）要求二次确认，未确认不派发；该守卫位于 POST 守卫链最前（running 守卫之前）。

## 溯源

- 2026-10-06 add-code-review-ratelimit-resume（spec/archive/2026-10-06-evo-add-code-review-ratelimit-resume） — 新建本能力：429 归因双源（result 事件兜底）、手动通道统一消费（共享配额防叠加）、分片剃余续跑与核销覆盖完整性门、手动 full 触发 open 阈值确认；起因是手动全仓审查死于账户级 429 后归因丢失、手动通道不消费重派意图、全量重跑重烧成本
