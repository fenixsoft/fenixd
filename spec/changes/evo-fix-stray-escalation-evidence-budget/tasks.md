## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_stray_untracked_evidence_budget.py
  kind: new
```

## 1. 证据体量预算

- [x] 1.1 core/worktree_manager/stray_wip.py：「条目体积(字节)」段（:2077-2078）套用与文件清单段（:314-321，EVIDENCE_MANIFEST_PREVIEW_LIMIT）同型的头部 50 项截断＋「等 N 项」＋体积合计聚合，全量体积引 sizes_bytes 注册表单源（写 :1134／读 :2068），不在 evidence 内联。「文件清单(N):」段保持原样（parse_stray_wip_manifest 写读成对不受影响）。
- [x] 1.2 core/agent_runner/prompt_builder.py：administrator 信号值装配处（:488-507，{evidence} 于 :499）加防御性体量上限，超限 fail-open 截断并附「已截断」注记，保证注入后提示词长度有界（截断须发生在 :516 `_fill_and_scan_placeholders` 单趟 re.sub 填充之前）。

## 2. 处置失败兜底

- [x] 2.1 core/admin_monitor.py：在孤儿处置恢复巡检（`_recover_orphaned_dispositions`）内，把「final 处置组（result="failed"，:6650-6689 落账）∧ 终态签名 prompt_too_long/api_error_status=400（run 转录 result 事件，parse_api_error_status 单源判定）」纳入与 interrupted 分支同型的限次重派（复用 `_reschedule_count_for`/reschedule_max），重派携带瘦身 evidence；同步修复 daemon 级 spec 记法关联失配（SIGNAL 记录 spec=None vs 组记录 spec=<项目名>，`_normalize_orphan_group_spec` 只归一 None↔"global" 致 unhandled_signal_for 恒不命中——2026-10-24 事故零升级根因），保证重派与升级判定对散件信号可达；限次用尽落 severity=critical 的 ESCALATION（不带 next_retry_at、不进派发失败自动重试扫描；与 `_converge_final_orphan_group` ⑥ 收敛升级共用 unhandled_for 去重，不双升）。

## 3. 契约测试

- [x] 3.1 tests/test_stray_untracked_evidence_budget.py：覆盖万项级清单信号 evidence 总量有界、51054 项形态注入不撑爆处置提示词、体积段截断与 manifest 解析写读成对、prompt_too_long 终态（final failed 组）触发限次重派且用尽后产生 critical 升级信号、daemon 级失配形态（SIGNAL spec=None＋处置组 spec=<项目名>）下重派/升级判定仍可达、用尽升级记录不带 next_retry_at 且不被 `_retry_due_dispatch_failures` 选中。
