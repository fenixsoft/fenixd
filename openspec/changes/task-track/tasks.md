# Tasks: task-track

## Deliverables

```yaml
- path: .fenix/bin/fenix_spec.py
  kind: modify
- path: core/deliverables.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: .fenix/bin/fenix_process.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: modify
- path: tests/test_task_track.py
  kind: new
```

## 1. 写入端格式固化（tasks-md-tracking R1）

- [ ] 1.1 `.fenix/bin/fenix_spec.py` 的 tasks artifact instruction 文本：guidelines 中新增 MUST 条目——分组标题必须为 `## <编号>. <标题>`（阿拉伯数字编号 + 点号），说明下游解析器（CLI/dashboard）与晋升 lint 依赖该格式、偏离将致任务清单不可跟踪；template 字段分组标题确认均为 `## <数字>. ` 形态
- [ ] 1.2 单测：调用 `instructions(project_root, "tasks", <change>)` 断言 instruction 含「MUST」「编号」「点号」与正确示例 `## 1.`、template 分组标题匹配 `^## \d+\. `；存量 status/instructions 行为零回归

## 2. 晋升 lint 拦截（tasks-md-tracking R2）

- [ ] 2.1 `core/deliverables.py` 新增 `lint_tasks_parseable(spec_dir, project_root) -> list`：tasks.md 不存在返回 `[]`；存在但按下游同源正则（分组 `^##\s+\d+\.?\s+` + 任务项 `^- \[(x| )\]`）解析出 0 分组 → 返回含「tasks.md」字样的违规消息；正则字面量两处注释互指（`data.py:parse_tasks` ↔ 本函数）
- [ ] 2.2 `core/pm_engine/engine.py:_on_spec_drafted` 在既有 `_lint_deliverable_declarations` 后并列调用新 lint，违规合并写 error（保持 drafted），异常 fail-open（WARNING + 放行），沿用既有日志风格
- [ ] 2.3 单测：无编号分组（`## 事项`）→ 晋升被拒、STATE error 含「tasks.md」、状态保持 drafted、不派发；`## 1. 标题` 与 `## 1 标题` 双格式 → 不拦；lint 抛异常 → 放行；修正后重新晋升成功
- [ ] 2.4 存量零误拔回归：脚本枚举 `openspec/changes/`（含 archive）全部 tasks.md 跑 `lint_tasks_parseable`，断言 0 违规；结果留验证记录

## 3. 解析端显式提示（tasks-md-tracking R3）

- [ ] 3.1 `.fenix/bin/fenix_process.py`：tasks.md 存在但解析为空 → 打印 YELLOW 警告行（含「tasks.md」「未解析出任务」字样）；文件不存在维持现状；正常解析无警告
- [ ] 3.2 `core/dashboard/data.py` spec 详情组装新增 `tasks_note` 字段：tasks.md 存在且 `parse_tasks` 为空 → 提示文本「tasks.md 存在但未解析出任务分组（分组格式不匹配或文件为空）」，否则 `None`
- [ ] 3.3 `core/dashboard/static/src/pages/projects/detail.tsx` 任务清单 Card 空态三分支：`tasks_note` 非空 → warning 提示（文案含检查分组格式指引）；无 tasks.md → 维持 secondary「暂无任务清单」；正常解析路径零变化
- [ ] 3.4 重建 `core/dashboard/static/dist/` 并随实现分支提交（v3 入库产物，漏建致 UI 验证假阴性）

## 4. 验证与回归

- [ ] 4.1 全量单测通过（`tests/test_task_track.py` + 既有 test_deliverables/test_pm_engine/test_dashboard_data 相关用例零回归）
- [ ] 4.2 真实环境验证：worktree 验证实例（非主树 :8787）执行 planner 验证场景——CLI 三态（正常/空解析/无文件）、dashboard 详情页三分支（A 正常/B warning/C 暂无）、run-lifecycle-hardening 17/17 回归
- [ ] 4.3 提交与收工：按任务粒度逐项 commit（`[fenix] task-track: <任务描述>`），tasks.md 逐项勾选，收工守卫 Deliverables 对账通过
