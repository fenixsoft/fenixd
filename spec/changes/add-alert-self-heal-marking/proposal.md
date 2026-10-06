## Why

告警自动闭环机制（add-alert-auto-resolve，`core/alert_lifecycle.py`）条件枚举保守，仅覆盖 spec 附着族（verify_fail_escalation / blocked_stuck / spec_content_missing / spec_delivered_no_content）；基础设施瞬态族的告警——daemon_errors 指纹风暴、spec-review infra 熔断（run_infra_failure）、evo 分析 run 失败、处置收敛升级（「处置终态未收口」）——全部不在册，永不自动闭环。这四族的共同形态是**底层故障自愈型**：风暴过去即恢复，但告警本体无人收口，长期滞留待处理队列。2026-10-06 实测 8 条未处理告警中 5 条属此族（两条「处置终态未收口」的底层风暴均已安静 10 小时以上，仍占人工甄别面），用户需在大量告警中人工识别哪些真需要介入。

## What Changes

- `core/alert_lifecycle.py` 新增自愈闭环条件族 `infra_transient_self_healed`：**签名安静判定**——条目（或其 `admin_run_id` 引用的底层 signal 条目）最近一次复现时刻（`last_seen`，缺失回落 `created`）距当前时刻 ≥ 安静窗口（默认 1440 分钟，可配）即视为已自愈。判定输入（告警列表、当前时刻）全部由调用方注入，模块保持纯函数、不读写文件。
- 覆盖族注册表 `SELF_HEAL_SIGNAL_TYPES`：daemon_errors、run_infra_failure、evo 分析 run 失败（写入点 `_evolution_warn` 的 signal_type）；收敛升级 escalation 经「引用条目安静」规则覆盖。**排除项不变**：inconclusive_loop env 握手族永不自动闭环（既有契约）；spec 附着族仍走既有条件；`handled=True` 人工记录不可覆盖。
- `AdminStore` 新增自愈写回路径：`handled_by="auto-self-heal"`、`resolve_note` 以「已自愈：」前缀附安静证据；可关闭 `kind ∈ {escalation, signal}` 的条目（既有 auto_resolve 仅 escalation）。**不触碰 disposition 记录本体**——AdminMonitor 生效核查的 fail-closed 契约（不补记 resolved）完整保留，自愈收口的只是人工待处理队列里的人脸条目。
- 存量回填：无 trigger 字段的 spec-less 条目按 signal_type ∈ 覆盖族推断（对齐既有 design D4 回填模式），当前积压告警（含两条滞留「处置终态未收口」）安静超窗后自动转入已处理。
- 巡检接线：`_run_alert_lifecycle` 扩展双通道（既有 spec 附着判定不变＋新 spec-less 自愈判定），挂既有巡检节拍不新增线程。
- 配置 `admin.self_heal_quiet_minutes`（默认 1440；非正整数/类型错误回退默认）＋ Dashboard 设置字段＋模板注释。
- Dashboard 运维记录：`handled_by=auto-self-heal` 渲染「已自愈」徽标（区别于既有 auto-resolve），条目自然落入已处理视图；待处理视图不再出现已自愈条目。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `alert-lifecycle`: 新增需求「基础设施瞬态告警自愈闭环」——条件枚举从「仅 spec 附着族」扩展到「spec-less 瞬态族按签名安静判定」；既有需求（触发条件结构化记录/条件解除自动闭环/闭环扫描时机与成本/存量告警回填/视图告警分组）语义不变，保守缺省（未识别 condition 永不自动闭环）不变。
