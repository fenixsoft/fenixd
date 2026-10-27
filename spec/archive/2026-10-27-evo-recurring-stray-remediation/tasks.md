## Deliverables

```yaml
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: agents/administrator.md
  kind: modify
- path: tests/test_adjudication_choices.py
  kind: modify
- path: tests/test_stray_untrack_remediation.py
  kind: new
```

## 1. untrack 裁决选项与执行器

- [x] 1.1 core/dashboard/data/adjudication_choices.py：maintree 桶（:292-294）新增 UNTRACK_STRAY_WIP 选项，沿 _COMMIT_STRAY_WIP（:101-108）的 spec_scoped=False + signal_type 绑定守卫先例，绑定 maintree_stray_wip_stale，语义「git rm --cached + .gitignore 根治」。
- [x] 1.2 core/dashboard/data/admin_actions.py：execute_adjudication_choice（:2879）新增 _exec_untrack_stray_wip 执行器——对告警指认文件清单执行 git rm --cached、.gitignore 追加（已存在则去重）、独立提交；复用 core/worktree_manager/stash_guard.py 的 staged 子集守卫/回滚子函数（:916/:1034 骨架；宿主装配沿 code_fix.py:2704-2706 的 `_Probe(G6StashGuardMixin)` 最小宿主先例，无需完整守卫实例），不打开其「check-ignore 全须忽略」前置门；结果记录 untrack 文件清单与提交号。

## 2. 复发识别与处置契约

- [x] 2.1 core/worktree_manager/stray_wip.py：_write_alert（:700-722）检索同文件历史 maintree_stray_wip_stale 告警与处置（admin_alerts 口径），第 2 次起在 evidence 带出「已 N 度处置」计数与根治指引（untrack 选项）。
- [x] 2.2 agents/administrator.md（:118 铁律区）：新增铁律——复发型主树散件（同文件第 2 次处置起）MUST 当场执行根治（untrack_stray_wip 或等效）或在处置记录挂显式跟踪项，MUST NOT 以「仅提交」第三次收尾；首次处置维持「提交+建议」现状。

## 3. 测试

- [x] 3.1 tests/test_adjudication_choices.py：扩 UNTRACK_STRAY_WIP 用例——选项注册/resolve、signal_type 绑定守卫（非 maintree_stray_wip_stale 信号拒绝）、与 _COMMIT_STRAY_WIP 并存不冲突。
- [x] 3.2 tests/test_stray_untrack_remediation.py（新建）：临时仓库端到端——seed 被 track 的生成物文件→执行选项→文件脱离索引、.gitignore 增行（重复执行不重复写）、独立提交生成、结果含清单与提交号；stray_wip 复发计数——同文件两次告警后 evidence 含「已 2 度处置」。