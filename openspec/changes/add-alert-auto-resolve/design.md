# Design: add-alert-auto-resolve

## Context

升级告警由 `pm_engine._send_human_escalation_alert`（.fenix/core/pm_engine.py:1079）经 `AdminStore.append`（.fenix/core/admin_store.py）写入 `.fenix/admin_alerts.json`，条目已有 `handled` / `handled_at` 字段但仅人工路径会写。告警产生后与底层 spec 状态完全脱钩——spec 恢复、验证通过、到达 pushed 都不会回写告警。`admin_monitor.py` 与 Dashboard admin 页直接消费该文件。

## Goals / Non-Goals

- Goals：条件解除自动闭环；存量回填；视图分组降噪；零新增配置键
- Non-Goals：不改变告警的产生条件、格式与去重/冷却机制；不做告警持久化格式迁移（沿用现有 JSON 结构，只增字段）；不实现通知撤回

## Decisions

### D1 闭环引擎挂在 AdminStore，触发点内联既有扫描
新增 `.fenix/core/alert_lifecycle.py`（纯函数判定 + 批量闭环），由 pm_engine 既有周期扫描调用。不新增线程/定时器——闭环判定复用扫描已有的 STATE.md 读取结果，成本 O(未闭环告警数)。告警全闭环时跳过写回（mtime 不变）。

### D2 结构化 trigger 字段，写入时埋点
`_send_human_escalation_alert` 增加可选 `trigger` 参数并落到条目：`{"type": signal_type, "spec": spec_name, "condition": "<闭环判定标识>"}`。首发只支持一种 condition：`spec_terminal_or_unblocked`（verify_fail_escalation / blocked_stuck 均属此类——spec 到终态或离开 blocked 即视为解除）。后续新告警类型按需扩展 condition 枚举，未识别的 condition 永不自动闭环（保守默认）。

### D3 自动闭环的标注语义
`handled=True` + `handled_by: "auto-resolve"` + `handled_at: <解除时刻>` + `resolve_note: "<依据，如 'spec v2-x 已到达终态 pushed'>"`. 闭环扫描 MUST 跳过任何 `handled=True` 条目（人工记录不可覆盖）。判定所需的 spec 状态以当轮扫描读取的 STATE.md 为准，不额外读文件。

### D4 存量回填 = 首启一次性推断
daemon 启动扫描首轮回填：对 `handled=False` 且无 `trigger` 字段的存量告警，按 `signal_type ∈ {verify_fail_escalation, blocked_stuck}` + `spec` 字段存在推断为 `spec_terminal_or_unblocked` 并执行同一判定；推断失败的（无 spec 字段或未知 signal_type）保持原状。回填与常态闭环共用同一代码路径，`resolve_note` 注明「存量回填」。

### D5 视图分组走既有 admin 页数据管道
Dashboard admin 页告警列表渲染时按 `handled` 拆两组：待处理（handled=False）默认展开置顶；已解决（handled=True，按 handled_by 区分「自动解决/人工处理」徽标）折叠为「已解决 (N)」可展开区，展开项显示 resolve_note 与 handled_at。不改 admin_alerts.json 读取路径，仅前端分组。

### D6 并发与文件安全
admin_alerts.json 已有原子写（tmp + rename）与 .lock 文件；闭环写回复用 AdminStore 的存储方法（不绕过锁）。pm_engine 扫描与 Administrator agent 处置可能并发写——闭环只改 handled 族字段且逐条幂等，竞态影响限于重复标注，可接受。

## Risks / Trade-offs

- 推断式回填可能把「确实曾被人工搁置」的历史告警也闭环 → resolve_note 明确标注 auto-resolve 与回填来源，人工可在视图中辨识；不丢失任何数据
- condition 枚举保守起步（仅 1 种），新告警类型需手动接入 → 接入点集中在 _send_human_escalation_alert 一处，成本低
- 未识别 condition 永不闭环的保守策略可能留下少量永久未闭环告警 → 视图中归入「待处理」会暴露问题本身，可接受

## Migration Plan

1. 新增 alert_lifecycle.py + _send_human_escalation_alert 埋点 + 扫描接入（一次提交）
2. 启动首轮回填自动处理存量（本次 6 条过时告警应被闭环）
3. Dashboard 分组渲染跟进
无数据迁移、无配置变更、无停机。

## Open Questions

（无——优先级 P9，范围按最小闭环裁剪）
