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

- [ ] 1.1 core/worktree_manager/stray_wip.py：「条目体积(字节)」段（:2019-2020）套用与文件清单段同型的头部 50 项截断＋「等 N 项」＋体积合计聚合，全量体积引 sizes_bytes 注册表单源（:1931），不在 evidence 内联。
- [ ] 1.2 core/agent_runner/prompt_builder.py：administrator 信号注入分支（:479/:496）加防御性体量上限，超限 fail-open 截断并附「已截断」注记，保证注入后提示词长度有界。

## 2. 处置失败兜底

- [ ] 2.1 core/admin_monitor.py：把 interrupted 限次重派通道（:5217-5385，reschedule_max）扩展覆盖 terminal_reason=prompt_too_long 与 api_error_status=400 终态形态，重派携带瘦身 evidence；限次用尽产生处置失败升级信号（落 ESCALATION，保证 :4881 派发失败重试扫描可达）。

## 3. 契约测试

- [ ] 3.1 tests/test_stray_untracked_evidence_budget.py：覆盖万项级清单信号 evidence 总量有界、51054 项形态注入不撑爆处置提示词、体积段截断与 manifest 解析写读成对、prompt_too_long 终态触发限次重派且用尽后产生升级信号。
