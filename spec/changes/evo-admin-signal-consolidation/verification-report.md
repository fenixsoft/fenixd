# 验证报告：evo-admin-signal-consolidation

> ⚠️ 本报告由框架于 2026-09-15T00:37:26Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-15T00:30:04.328723+00:00

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 17/18 场景通过，1 失败，0 错误（1 个真实产品 Bug）**

回归组 1/36 失败：test_append_serializes_non_string_evidence。AdminStore.append 写入口未将 dict/list evidence 序列化为 JSON 串，rec["evidence"] 保留为 dict，违反 evidence 字符串契约（回归 fix-alert-evidence-render-crash）。其余 17 场景 35 断言全过。

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 6.21M |
| 本链增量 Token（输出） | 0.07M |


## 真实产品 Bug

### BUG-01（severity=major）· exit_code / output_match

- 关联场景：reg-admin-store-throttle-disposition-suite
- 描述：AdminStore.append 不序列化非字符串 evidence：dict/list 类型 evidence 直传落盘与读出，违反 evidence 恒为 str 契约，读侧（Dashboard API / prompt 注入）将收到对象类型，可能复现 fix-alert-evidence-render-crash 的白屏崩溃（该回归测试在 main 工作树存在且失败）。
- 根因：core/admin_store.py _normalize_entry 仅 setdefault("evidence", None)，append/merge_signal 写路径无 json.dumps 序列化非字符串 evidence 的分支
- 证据（场景 reg-admin-store-throttle-disposition-suite 结构化证据，引用）：
  - failed_assertions: [{"type": "exit_code", "expected": 0, "actual": 1, "message": "pytest 退出码 1"}, {"type": "output_match", "mode": "contains", "expected": "36 passed", "actual": ".F.F................................... [100%] FAILURES"}, {"type": "output_match", "mode": "negate FAILED", "expected": "不包含 FAILED", "actual": "FAILED tests/test_admin.py::TestAdminStore::test_append_serializes_non_string_evidence"}]
  - screenshots: []
  - first_failed_step: 步骤1: python3 -m pytest tests/test_admin.py::TestAdminStore ... 退出码 1，test_append_serializes_non_string_evidence 失败


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| ut-store-merge-signal-suite | 单元测试·merge_signal 状态沉淀全组 8 条：首见建记录带 status_hash/last_seen、状态未变仅刷 last_seen 不新增、状态变化新建、不同 spec/signal_type 新建、escalation/disposition 永不合并、STORED_SIGNAL_TYPES 写入即待唤起记录不合并、escalated 单调升级不回退、spec=None daemon 级沉淀（tests/test_admin.py:315-482 TestAdminStore；实现点 core/admin_store.py:166-215 merge_signal） | pass | 0/3 | - |
| ut-store-latest-signal-suite | 单元测试·latest_signal 冷却窗口锚点全组 8 条：窗口内命中/窗口外忽略、max(created,last_seen) 锚点跨 cooldown 仍命中节流、无 last_seen 历史记录仍按 created 判定、4 个外部调用点（dispatch_stalled/instant_fail_storm/transient_break_storm/verify 告警）窗口语义不变（tests/test_admin.py:484-520+ TestAdminStore；实现点 core/admin_store.py:333-387 latest_signal） | pass | 0/3 | - |
| ut-monitor-signal-consolidation-suite | 单元测试·监控信号状态沉淀 + 悬置强制升级全组 8 条：状态未变多轮巡检单记录不重唤起、error 并入 status_hash 状态变化新建、daemon spec=None 指纹沉淀、9.5h 悬置重放 ≤2 条且单唤起、blocked <2h 不强制升级、未处理升级存在不新增、人工 handled 后仍悬置可再升级、非悬置类信号不外溢（tests/test_admin.py:878-1030 TestSignalConsolidation） | pass | 0/3 | - |
| ut-dual-dispatch-frozen-invoke-regression | 单元测试·dual-dispatch/freeze 全组 24 条回归：唤起分支由 append 改走 merge_signal 二元组后 MagicMock store 兼容（test_dual_dispatch_and_freeze.py:326-333 回归修复点 57ced064），防并发调度/冻结语义被沉淀改动破坏 | pass | 0/3 | - |
| int-store-merge-unchanged-last-seen-only | 真实对象集成·R1 状态沉淀正向路径：真实文件落盘 AdminStore，同一 (spec, signal_type, status_hash) 两次 merge_signal → 不新增记录、is_new 首真次假、仅刷 last_seen、id/created(first_seen)/escalated/handled 不变（core/admin_store.py:166-215 merge_signal） | pass | 0/9 | - |
| int-store-merge-state-change-new-record | 真实对象集成·R1 状态变化异常路径：status_hash 变化（spec 状态/error/updated 并入 hash）、不同 spec、不同 signal_type → 均新建记录，互不合并（core/admin_store.py:166-215；core/admin_monitor.py:783-817 _signal_status_hash） | pass | 0/5 | - |
| int-store-merge-never-merges-protected-records | 真实对象集成·R1 保护语义：kind=escalation 与「写入即待唤起」(STORED_SIGNAL_TYPES=family_explosion 等, core/admin_monitor.py:161) 记录永不参与合并（不被追加 status_hash/last_seen、severity/escalated 不改写）；escalated 仅单调升级 False→True、绝不 True→False 回退（core/admin_store.py:166-215） | pass | 0/8 | - |
| int-store-latest-signal-anchor-window | 真实对象集成·R1 冷却锚点迁移：created 60m 前 + 合并续刷 last_seen → 15m 冷却窗口仍命中（锚点=max(created,last_seen)）；无 last_seen 历史记录按 created 判定（15m 不命中、61m 命中）（core/admin_store.py:333-387 latest_signal） | pass | 0/6 | - |
| int-store-daemon-spec-none-consolidates | 真实对象集成·R1 spec=None daemon 级信号按声明口径沉淀：同 (None, signal_type, hash) 仅维护一条记录（id 不变）、hash 变化新建；无 KeyError/无意外合并（core/admin_store.py:166-215；admin_monitor.py:808-817 daemon 指纹回退判据） | pass | 0/7 | - |
| int-monitor-9-5h-stalled-replay | 真实对象集成·验收场景 1（add-web-ui 9.5h 悬置重放）：真实 AdminMonitor+AdminStore+假 runner，blocked 悬置 9.5h、cooldown 15m、5 轮巡检 → 信号记录 1 条（≤2）、强制升级恰 1 条（severity critical、signal_type=blocked_stuck、evidence 含悬置时长 570 分钟/updated/信号首见）、Administrator 仅唤起 1 次、无升级风暴（core/admin_monitor.py:900-960 _force_escalate_stalled；spec.md 验收标准） | pass | 0/11 | - |
| int-monitor-cross-cooldown-no-reinvoke | 真实对象集成·验收场景 2（跨 cooldown 不重唤起）：已唤起信号 created 30m 前（>15m cooldown）且 last_seen 经沉淀续刷为 now → latest_signal 锚点覆盖 last_seen 命中节流、下一轮巡检不重唤起；对照差异对：last_seen 同样陈旧（无续刷）→ 节流失效正常唤起——证明锚点修复真实生效、测试非空转（core/admin_store.py:333-387；admin_monitor.py:875-896 _throttled） | pass | 0/5 | - |
| int-monitor-daemon-spec-none-consolidation | 真实对象集成·验收场景 3（spec=None daemon 级沉淀）：真实 AdminMonitor 巡检 daemon_errors（_detect_daemon_errors 携带稳定 _fp 指纹）→ 同指纹多轮仅 1 条记录、不重复唤起、无 KeyError；不同错误指纹 → 新建记录（core/admin_monitor.py:783-817 _signal_status_hash 回退判据） | pass | 0/6 | - |
| int-monitor-force-escalation-boundaries | 真实对象集成·R2 强制升级范围边界：blocked 悬置 <2h（90m）不触发强制升级（仅正常唤起一次）；非悬置类信号（stuck）悬置 >2h（9h）不触发强制升级、维持既有 cooldown 节流——范围仅限 blocked_stuck+ENV 阻塞族不外溢（core/admin_monitor.py:900-960、STALLED_ESCALATION_SIGNAL_TYPES:51） | pass | 0/5 | - |
| int-monitor-escalation-storm-guard | 真实对象集成·R2 升级风暴防护与人工闭环：已存在未处理人工升级告警时多轮巡检不新增强制升级、不唤起 Administrator；人工 mark_handled 后状态仍悬置 ≥2h → 恰再升级一条（每次人工处理后至多一条），Administrator 全程不重复唤起（core/admin_store.py:389-405 unhandled_for；admin_monitor.py:939-944 未处理约束） | pass | 0/5 | - |
| static-handle-signal-merge-routing | 静态保真·_handle_signal 两处落库（节流分支/唤起分支）均经 merge_signal 沉淀、无直接 append 残留——「同状态不逐轮新增记录」在实现层成立（core/admin_monitor.py:833-888） | pass | 0/3 | - |
| static-stalled-escalation-module-constant | 静态保真·R2 阈值 2h 为模块常量 STALLED_ESCALATION_MINUTES=120（core/admin_monitor.py:72）、不进 config（core/config.py:928-958 get_admin_config 无相关键——规避「新增配置项必须带 Dashboard UI」约束） | pass | 0/3 | - |
| static-r3-observability-no-new-endpoint | 静态保真·R3 可观测不新增 dashboard 聚合端点：自省报告 admin 摘要「信号 N 条」仍由 store.read_all 按 kind=signal 计数（core/self_review.py:683-695）、core/dashboard/server.py 无新增 signal 列表端点（无信号消费端即死代码，design.md R3 非目标） | pass | 0/3 | - |
| reg-admin-store-throttle-disposition-suite | 回归·admin store/节流/处置闭环相邻测试 36 条全通过：TestAdminStore 全组（含 latest_signal 4 外部调用点）、TestAdminMonitorThrottle 冷却节流与未处理抑制、TestEscalationClosedOnFinalDisposition 孤儿 escalation 闭环均不受沉淀改动影响（tests/test_admin.py） | failed（已修正） | 3/3 | product-bug |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

当前稳定场景集共 18 个（第 1 轮）。

- 首轮写入 18 个场景

