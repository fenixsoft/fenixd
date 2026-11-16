<!-- knowledge: capability=admin-monitor rev=2 sources=spec/archive/2026-09-22-evo-orphaned-state-probe-calibration,spec/changes/evo-daemon-errors-selfheal-exemption -->

# 异常状态探测口径（admin monitor 探针）

admin monitor 的无驱动探测口径：orphaned_state 孤儿态探测的可见性，与 daemon_errors 复现升级判据的自愈签名豁免面。

## 规则

- run_id 前缀归一按真源全量前缀（`core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES`）还原 spec 名：spec-review/repair/planner/admin 等全部 run 前缀都能还原；`_has_recent_spec_run` 据此识别活跃 run。
- 失败计数前缀子集与归一前缀分离：`_RUN_PREFIXES` 只作计入失败统计的前缀子集（含 `repair-`，不含 `planner-`/`test-`），前缀归一改造不连带改变 `repeated_failures` 计数口径。
- 进程存活探测 `_pgrep_live_worktree` 的匹配集覆盖 `repair-<spec>-`（含 event_bus 孪生）；orphaned_state 三条件判定结构不变（无活动 run / 无存活子进程 / 无待派发）——任一前缀（含 repair-）的 run 文件 mtime 在宽限内即非孤儿。
- admin 处置 run（run_administrator）非零退出时，失败证据包含原始 stderr 摘录、退出码、provider/model 与末 3 条带 timestamp 的事件时间线；原始 stderr 只进证据字段，不回填 error 归因文本（error-attribution-denoise 的降噪语义保持）。
- 告警生命周期语义：signal / disposition pending / disposition failed / escalated 属同一信号的不同阶段，阶段差异由 description 与 status 区分；窗口查重（`AdminStore.latest_signal` → `_throttled`）冷却过期后同信号重新成条属既有语义，不视为重复告警缺陷。
- daemon_errors 升级判据由单源自愈签名注册表（`SELF_HEAL_ERROR_SIGNATURES`，模块级常量不入 config；条目 = name / component / message 前缀 / 自愈消费者说明）豁免已知自愈链路的重复 ERROR 留痕：命中签名跳过 critical 升级与「建议重启 daemon」文案，与既有压制面（窗口阈值/最近间隔判据、重启冷却窗、孪生指纹合并）同层共存且互不影响。
- 现行注册两个签名：`wip-overlap-precheck-escalate`（component=worktree_manager，消费者=WIP 等待周期消费者 / merge-only 重试 Timer 自动合回，预算 90 分钟窗口 / 6 轮超限降级人工）；`promotion-lint-failed`（component=pm_engine，消费者=promotion 恢复节拍自动重试 lint，长期停摆由每日龄期盘点兜底可见）。
- 豁免只压制升级告警：ERROR 日志行保留可检索，daemon_errors 既有判定行为（窗口阈值/最近间隔判据、重启冷却窗、孪生指纹合并）照常运转；窗口内复现与跨日同刻复发两个升级维度对豁免签名一律跳过。
- 跨日复发维度的可见度兜底 = 消费端预算超限降级人工告警 + 命中审计计数；自愈消费者停摆演成真故障时，超限后的新形态 ERROR（换签名/持续超窗）不受豁免影响仍会升级。
- 豁免命中留可审计计数（`get_selfheal_exempt_hit_counts`），审计面区分「已豁免的自愈链路留痕」与「未豁免的真实错误」。
- merge-back precheck 重复拦截源头聚合：同一合回重试窗口内首条拦截保留 ERROR 作首阻取证（首阻记账 `_merge_retry_first_at` 承载，重试侧据其在场判别非首阻），后续重试落聚合 INFO 留痕（含 retry 序号与距首阻间隔），不重复进 daemon_errors 复现计数；「Merge-back blocked」文案全仓唯一消费者即该日志行本身，降级无下游解析破坏面。

## 代码锚点

- 主实现：`core/admin_monitor.py`（`_detect_daemon_errors` 升级判定、`SELF_HEAL_ERROR_SIGNATURES` 注册表与签名匹配、命中审计计数）
- 注册表先例参照：`core/alert_lifecycle.py`（`SELF_HEAL_SIGNAL_TYPES`）
- 源头聚合：`core/worktree_manager/mergeback.py`（escalate 拦截出口日志分级）
- 自愈消费者：`core/pm_engine/dispatch/queue.py`（WIP 等待周期复查与 merge-only 重试）
- 守卫测试：`tests/test_daemon_errors_selfheal_exemption.py`

## 溯源

- 2026-09-22 evo-orphaned-state-probe-calibration（spec/archive/2026-09-22-evo-orphaned-state-probe-calibration） — 修复活跃 repair run 双探测失明的误报：前缀归一全量化、存活探测覆盖 repair、admin 失败 run 证据补全与信号生命周期语义文档化
- 2026-11-16 evo-daemon-errors-selfheal-exemption（spec/changes/evo-daemon-errors-selfheal-exemption/） — 新增 daemon_errors 升级面的自愈签名豁免注册表（压制升级不删日志+审计计数）与 merge-back 重复拦截源头聚合落行
