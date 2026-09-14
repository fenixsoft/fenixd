# 设计 — admin-signal-consolidation

## 记录模型
- admin_alerts 信号记录增加 status_hash（sha1(spec.status + error + updated)）、first_seen、last_seen；first_seen 即现有 `created`（保留首次语义），last_seen 为最近一次同状态发生时间。
- 去重仅作用于 **admin_monitor 的 per-spec 检测信号**（`_handle_signal` 的两处 append）。合并只更新 last_seen，MUST NOT 改写 id / created / escalated / handled。
- 去重 MUST NOT 作用于「写入即待唤起」型记录（pm_engine、dashboard UI、merge-back 等直接 `AdminStore.append` 写入、由 `STORED_SIGNAL_TYPES` 按 id 摄取并 `mark_escalated` 的记录，admin_monitor.py:434-500）：其 id 是 `mark_escalated` 的锚点，被合并/替换会触发「该记录可能被反复摄取」重复唤起。
- 去重 MUST NOT 作用于 `kind=escalation`：人工资讯告警由 `latest_signal` 做冷却查重（verify_report.py:704、agent_runner/runner.py:4014、agent_runner/provider_circuit.py:446），跨事件合并会破坏 `mark_handled` / `auto_resolve` 的按 id 闭环语义。
- 实现为 AdminStore 的新增 per-spec 方法（如 `merge_signal`），**不改 `append` 的全局语义**；`latest_signal` 的窗口判定一并调整（见下）。

## 冷却锚点迁移（必须，否则回归）
- `AdminStore.latest_signal` 现按 `created` 判定窗口（core/admin_store.py:277-312），`_throttled` 依赖它（core/admin_monitor.py:792-798）。沉淀后 `created` 停在首次，一旦超过 cooldown（缺省 60m）便不再被命中 → 节流失效 → 每轮巡检重新唤起 Administrator，比现状更烧钱。
- 故 `latest_signal` 的窗口判定 MUST 改为 `max(created, last_seen)`（无 last_seen 的历史记录仍按 created 判定）。该 API 有 4 处外部调用点（core/pm_engine/recovery.py:290、core/agent_runner/provider_circuit.py:446、core/verify_report.py:704、core/agent_runner/runner.py:4014），改动须保证其语义不变。
- `spec=None` 的 daemon 级信号（daemon_errors / restart_failed / UI 手动信号）同样按 (spec=None, signal_type) 沉淀；此类无 spec.status/error/updated，status_hash 回退为 daemon 级判据（error 指纹 + 时间桶），或显式声明不纳入沉淀——二者择一，MUST 在实现里明示，不得留空。

## 强制升级判据
- 范围限定为**悬置类信号**：blocked_stuck（含 ENV 阻塞族），对齐 proposal「blocked 悬置 ≥2h」。其他信号类型（stuck/flapping/repeated_failures/daemon_errors…）维持既有 cooldown 节流，不得外溢——否则任何持续 >2h 的常规信号都会绕过 Administrator 直接冲人工。
- 悬置时长口径 = `now − spec.updated`（spec 保持同一 blocked 状态的时长，对齐 proposal/验收的「blocked 悬置 9.5h」），**不是**信号记录 first_seen（后者含 max(cooldown,15) 阈值延迟，会晚一小时余才触发）。
- 触发动作 = **直接写一条 `kind=escalation` 人工告警**（severity critical，注明悬置时长与首次触发时间）；**不重新唤起 Administrator**（重唤起即重复烧钱，正是 cooldown 要防的）。
- 冷却与未处理告警必须区分：强制升级**绕过 `latest_signal` 冷却**，但 MUST 仍受 `unhandled_for` 约束——同 (spec, signal_type) 已有未处理人工告警时不再重复写，否则每轮巡检新增一条 ESCALATION = 升级风暴。人工把该告警标 handled 后、状态仍悬置且 ≥2h → 可再次升级（每次人工处理后至多一条）。
- 阈值 2h 为模块常量，不进 config（对齐 admin_monitor.py:49-52 既有做法，规避「新增配置项必须带 Dashboard UI」约束）。

## 改动点
- core/admin_store.py（`.fenix/core` 是指向 core/ 的符号链接，同一文件）：新增 per-spec 信号沉淀方法 + `latest_signal` 窗口改用 max(created,last_seen)。
- core/admin_monitor.py：状态哈希判定 + 悬置 ≥2h 强制升级（受 unhandled_for 约束）。
- 可观测性不新增 dashboard 聚合：dashboard 现不展示 `kind=signal` 记录（core/dashboard/data.py:91-154 的 admin activities 只取 disposition，时间轴 data.py:3200-3214 只取 escalation+disposition，无 signal 列表端点），「替代逐条刷屏」无既有消费端，新增聚合端点会成为死代码。R3 的可观测改由既有消费端覆盖：自省报告 admin 摘要的「信号 N 条」（core/self_review.py:688）与 MAX_RECORDS=150 裁剪窗口（core/admin_store.py:31-34）自然反映沉淀效果。若后续确需 UI 展示，另行立项并同时声明 server.py 与前端落点。
