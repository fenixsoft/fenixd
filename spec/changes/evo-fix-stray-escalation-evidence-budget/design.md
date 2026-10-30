# 设计：stray-escalation-evidence-budget

> 行号基准：2026-10-30 工作区（评审取证后勘误；机制断言均经代码与 2026-10-24 事故实证核对）。

## 改动点

1. core/worktree_manager/stray_wip.py — 体积明细段截断
   - 「条目体积(字节)」段（:2077-2078，`_write_untracked_escalated_alert` 内全量 `', '.join(f'{k}={v}' ...)`，51054 项形态实测撑出 6.6MB evidence）套用与文件清单段（:314-321，EVIDENCE_MANIFEST_PREVIEW_LIMIT=50）同型的头部 50 项截断＋「等 N 项」＋体积合计字节聚合。
   - 全量体积已有注册表单源（写入 :1134 `entry["sizes_bytes"]`，读侧 :2068），evidence 只引注册表不内联全量。该段现无任何解析侧消费方（全库仅写侧一处），截断不涉写读成对改造；「文件清单(N):」段保持原样（`admin_actions.parse_stray_wip_manifest` 成对消费与复发计数、认领执行器清单来源不受影响）。
2. core/agent_runner/prompt_builder.py — 注入侧上限
   - administrator 信号值装配处（:488-507 values dict，{evidence} 在 :499）对 {evidence} 值加体量检查：超过上限（如 200KB）fail-open 截断＋「[evidence 已截断：原 N 字符]」注记，防任意信号类型同型撑爆。截断发生在 :516 `_fill_and_scan_placeholders`（单趟 re.sub，注入值不重扫）之前，截断注记不含占位符字面量，残留扫描告警语义不变。
3. core/admin_monitor.py — 处置失败兜底
   - 扩展点勘误（关键）：prompt_too_long/api 400 死亡的处置 run 由 admin `_worker` 落 **final** DISPOSITION（result="failed"，:6650-6689），组经 `_merge_admin_runs`（:1049-1054，任一非 pending 记录即 final）判为 final，走 `_converge_final_orphan_group`（:5594），**不会**到达 interrupted 分支（:5355 `_run_has_interrupted_marker` 门）。故本改动在孤儿处置恢复巡检（`_recover_orphaned_dispositions`，:5232 起）内，把「final 组 ∧ 终态签名＝prompt_too_long/api_error_status=400」纳入与 interrupted 分支（:5355-5399）同型的限次重派机制（`_reschedule_count_for` :5208 / reschedule_max property :1551-1553），而非只改 interrupted 分支条件。
   - 终态签名检测：run 转录 result 事件 `terminal_reason="api_error"`＋`api_error_status=400`（事故实证实录 `.fenix/runs/archive/admin-fenixd-1792880308.jsonl`），复用 `provider_circuit.parse_api_error_status` 与 `_admin_run_file`（:6159，含 archive 回退）既有单源；处置记录 error/failure_evidence 仅 generic 文案（实查为 "claude CLI failed: Exit code: 1…"），不得作为唯一判据。
   - **daemon 级 spec 记法关联约定（本改动成立的关键前提）**：散件升级信号 SIGNAL 记录 spec=None（escalated=true、handled=false），处置组记录 spec=<项目名>（`_worker` :6654 `signal.get("spec") or disp.spec` → 'fenixd'）。既有 `_normalize_orphan_group_spec`（:920-939）只归一 None↔"global"，项目名形原样透传；`unhandled_signal_for`（admin_store.py:1096-1110）spec 严格相等 → **恒不命中**。2026-10-24 事故实证：该组仅 pending+final failed 两条、零 ESCALATION——孤儿收敛升级（`_converge_final_orphan_group` ⑥，:5669-5707）与重派判定均被此失配静默致盲，即 46h 悬空根因。重派实现 MUST 同步补齐该记法的关联口径（如对 daemon 级信号类型按 (signal_type, 信号 spec=None) 宽口径关联，或扩展归一函数覆盖项目名形），并维持 ⑤ 在飞互斥（:5664）、① 幂等（:5634）、unhandled_for 升级去重语义不变。
   - 重派携带瘦身 evidence（依赖改动点 1/2 生效；注入侧上限对存量肥大信号同样兜底）。
   - 重派用尽后产生处置失败升级信号：severity=critical 的 ESCALATION（形态对齐既有中断超限先例 :5366-5394），**不带 next_retry_at**——不进入派发失败自动重试扫描（`_retry_due_dispatch_failures` :5017-5115 只消费带 next_retry_at 的未处理 ESCALATION，:7018/:7050-7055；其 DISPATCH_RETRY_MAX=1 独立于 reschedule_count 计数），与「重派至多 reschedule_max 次」约束一致；与 ⑥ 收敛升级共用 unhandled_for 去重锚点，MUST NOT 对同一信号双重升级。

## 数据流

散件越阈 → 升级信号构造（体积段截断＋聚合）→ Administrator 派发（注入侧上限兜底）→ 成功处置；失败（prompt_too_long/api 400 终态）→ 孤儿巡检识别 final failed 组（daemon 级 spec 关联修复后可达）→ 限次重派（瘦身 evidence）→ 用尽 → 处置失败 critical 升级（人工介入出口，不自动重试）。

## 边界与权衡

- fail-open（截断优于拒绝）：处置拿到缩水的证据也比链路死透好；全量明细经注册表仍可追溯。
- 重派仅 1-2 次（沿用 reschedule_max）：防对同一坏信号重派风暴；用尽后走人工升级而非继续自动重试——不搭派发失败重试扫描的便车，避免 reschedule_max 之外再叠加 DISPATCH_RETRY_MAX 突破重派总额。
- 只重派 API 400/prompt_too_long 形态：429/402/403 等已有瞬态归因与 provider 熔断语义（core/agent_runner/provider_circuit.py），不纳入本通道，防对限流/计费类错误重派烧钱。
- 不改升级触发阈值与「同一集合只升级一次」语义——本 SPEC 只保证失败后有兜底出口，不再依赖指纹消失前的带外救援。
