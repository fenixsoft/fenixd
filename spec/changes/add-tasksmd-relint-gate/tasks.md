# add-tasksmd-relint-gate tasks

## Deliverables

```yaml
- path: core/deliverables.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: tests/test_task_track.py
  kind: modify
- path: tests/test_tasksmd_relint_gate.py
  kind: new
```

## 1. lint 规则加强（TDD）

- [x] 1.1 写失败测试（tests/test_task_track.py 追加）：tasks.md 含合法分组但任务行全部为 `^- [x] 1.1 …` 损伤形态 → `lint_tasks_parseable` 返回 1 条违规，文案含「tasks.md」「任务分组」与 `- [ ]`/`- [x]` 修正处方；正常分组+任务行、tasks.md 不存在、0 分组既有形态三 Scenario 零回归
- [x] 1.2 实现：core/deliverables.py 抽模块级纯函数 `_tasks_parse_counts(text) -> tuple[int, int]`（返回分组数、任务行数，任务行按 `_TASKS_ITEM_RE` 计数）；`lint_tasks_parseable` 改用该函数，新增「分组 > 0 且任务行 == 0 → 违规」分支，文案点名 `^-` 损伤特征与修正处方
- [x] 1.3 全库存量自检：对 spec/changes 与 spec/archive 全部 tasks.md 跑加强后的 lint，零违规（零误拦证据写入测试注释即可，不做自动化扫描测试）

## 2. 复检门禁挂点（TDD）

- [x] 2.1 写失败测试（tests/test_tasksmd_relint_gate.py）：full 车道——implementer 成功、分支 tasks.md 带损伤前缀 → 不 merge、状态回 ready、error 含违规明细与处方、implementer 重新入队；分支 tasks.md 正常 → merge 正常执行；分支无 tasks.md → fail-open 放行；git show 失败 → fail-open 放行 + WARNING
- [x] 2.2 写失败测试：fast-track 车道——worktree 内 tasks.md 带损伤前缀 → `_keep_fast_track_worktree` + `_handle_fast_track_failure`、error 含违规明细与处方；worktree 内 tasks.md 正常或不存在 → 流程继续硬校验；lint 异常 → fail-open 放行 + WARNING
- [x] 2.3 实现 full 车道挂点：dispatch.py implementer 成功块（零变更哨后、交付物守卫同层）——`git show <branch>:spec/changes/<name>/tasks.md` 取分支版本文本，调用 `_tasks_parse_counts` 判定；违规 → 不合并不推进，error 写明细+处方，走既有失败重派；任何异常 fail-open
- [x] 2.4 实现 fast-track 车道挂点：`_run_fast_track_flow` 交付物守卫后、硬校验前——读 worktree 内 tasks.md 文本，同一判定；违规 → `_keep_fast_track_worktree` + `_handle_fast_track_failure`；任何异常 fail-open
- [x] 2.5 跑通 2.1/2.4 全部测试

## 3. 回归与收口

- [ ] 3.1 既有回归零破坏：tests/test_task_track.py、tests/test_deliverable_lint.py、tests/test_deliverable_gate.py、tests/test_fast_track*.py（如存在）全绿
- [ ] 3.2 自检：grep 确认 data.py / fenix_process.py 解析端零改动；复检挂点仅在 implementer 成功路径（full+fast-track）生效，verifier/repair/planner 车道不受影响；fail-open 语义两车道一致
