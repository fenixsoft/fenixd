## Why

2026-11-11 redesign-chain-panel-ui 事故实证：judge_rerun_cap 冻结 → arbiter 16:15:44Z 产出明确推荐（manual_fixed_reverify）→ 人工 02:29:14Z 才点击（空转 10h14m，点击内容=机器推荐原文，信息量 0）→ 解冻后再吃 7.5 分钟扫描延迟才派发重验。冻结到重验开跑全程 10h36m，其中机器有效产出集中在头 2 小时。白名单外冻结全部落为「pending 告警 + 无限期等人」，即使 arbiter 已完成完整调查、推荐动作本身可逆自限。人的稀缺注意力被消耗在机器已有答案的决策上，框架自主性在最常见事故形态上规律性破功。

## What Changes

- **裁决选项风险分级**：静态注册表每个 choice 增加风险档位字段——`reversible-experiment`（reset 类：清计数重验，失败自然再冻结再告警）/ `state-advance`（force_advance 类：带病推进）/ `terminal`（abandon 类：终局不可逆）。分级依据动作不可逆性，不沿用白名单内外一刀切。
- **推荐项到点自动执行（revocation-window auto-exec）**：arbiter 升级产生的 pending 人工告警，若满足判据（完整调查 ≥1 次且推荐明确、无共存更高严重度告警、本 spec 连续 auto-exec 未超上限缺省 2），在 grace 窗（缺省 30 分钟，自推荐可用时刻 arbiter_upgrade.upgraded_at 起算，无 upgrade 痕回退 created）结束时仍 pending 则自动执行推荐 choice；执行留痕与人工点击同构（actor=auto-policy），dashboard 可见不静默。grace 窗内人工可否决或改选（人工动作先到先得）。
- **human-only 档不受影响**：`state-advance` / `terminal` 档继续等人，但获得告警老化升级记录（pending 超阈值写高可见度升级事件），避免无声过夜。
- **外部 testing 跃迁即时派发**（配套）：dashboard 进程直写 STATE 产生的 `→testing` 跃迁经 watch 通道（2 秒级）即时触发 verifier 派发，不再等 30 分钟周期 full_scan 的 `_recover_testing` 兜底；幂等由既有无驱动判定吸收。
- 链序不变：Admin→Arbiter→人工的升级处置链、白名单调查语义、复现配额全部原样保留；本机制只改变链终点（人工出口）在「有明确推荐 + 可逆动作」时的等待语义。

## Capabilities

### New Capabilities

- `adjudication-auto-exec`: pending 升级告警的推荐项分级自动执行策略——判据、grace 窗、人工否决、连续上限、审计留痕、fail-open 降级、human-only 档老化升级、dashboard 展示（auto-executed 标注与 grace 倒计时）。
- `testing-dispatch-liveness`: 外部进程直写 STATE 的 testing 跃迁即时派发通道——watch 通道补 `testing` 事件映射或等价 kick，幂等由无驱动判定吸收，与 60 秒 ready 精触发、30 分钟 full_scan 兜底共存。

### Modified Capabilities

- `adjudication-choices-registry`: 静态注册表每个 choice 条目增加风险档位字段（`risk_tier`），档位取值 `reversible-experiment` / `state-advance` / `terminal`，与 signal_type→choices 映射同源单点维护；缺档位的历史条目按最保守 `terminal` 兜底（不自动执行）。

## Impact

- `core/dashboard/data/adjudication_choices.py`（注册表加 risk_tier 字段）
- `core/pm_engine/escalation_chain.py` / `core/admin_monitor.py`：预期零改或仅按需微调——判据①所需 arbiter 调查痕已在告警发射时携带（chain.arbiter_rulings / endpoint_kind 既有字段），risk_tier 由引擎读时从注册表解析（design 决策 1，不经发射点拷贝）；auto-exec 判定入口为新增 core/admin_auto_exec.py（design 决策 2），不落本条两文件
- `core/admin_choice_exec.py`（执行机器复用，新增 actor=auto-policy 留痕形态；预计小改或零改）
- 新增 auto-exec 策略引擎模块（daemon 侧周期扫描 pending 告警，判定 + 到点执行 + 审计写点）
- 前端告警卡片（auto-executed 徽标、grace 倒计时展示）：所需字段经 `core/dashboard/data/admin_alerts.py` 读时合并层透出（tasks 5.1），`core/dashboard/routes/alert_routes.py` 仅在排序/透传需要时按需微调，不作独立交付面
- `core/event_bus.py`（testing 跃迁 watch 通道派发）
- 不改变：链序与配额语义、人工 alert-resolve API 契约（人工动作仍即时生效且优先）、白名单调查面
- 关联知识页：admin-ops/escalation-chain.md、adjudication-choices-registry.md、arbiter-lane.md、alert-lifecycle.md；dispatch-scheduling/scheduling-kick-signal.md、full-scan-resilience.md
