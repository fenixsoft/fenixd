## Deliverables

```yaml
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: tests/test_dashboard_data.py
  kind: modify
```

## 1. 测试先行（TDD 红）

- [x] 1.1 `tests/test_dashboard_data.py` 新增 `spec_summary` 阶段判定用例：status=`testing` → `progress_phase: "verify"` 且 `verify_current` 透传进度文件 current 文案；status=`verified`/`done`/`pushed`/`bug-found`/`blocked`/`implementing` → 恒 `"impl"`（预期先失败）
- [x] 1.2 新增容错用例：testing 但进度文件损坏（`parse_verify_progress` 返回 error）→ `progress_phase` 仍 `"verify"`、`verify_current` 为空串、不抛异常
- [x] 1.3 新增 fast-track 恒 impl 用例：mode=fast-track 的 spec（`.spec.yaml` 带 mode 行）在 drafting/implementing/verified 各态 → `progress_phase: "impl"`（无需 mock 派发，仅验字段判定与 mode 无关）

## 2. 后端字段透传（TDD 绿）

- [x] 2.1 `core/dashboard/data.py` 的 `spec_summary`：返回 dict 新增 `progress_phase`（`"verify"` 仅当 `entry.get("status") == "testing"`，否则 `"impl"`）与 `verify_current`（`vp.get("current", "")`）；不新增 IO
- [x] 2.2 跑通 1.1-1.3 新用例及 `tests/test_dashboard_data.py` 既有全部用例（spec_summary 既有字段零回归）

## 3. 前端阶段分支渲染

- [x] 3.1 `core/dashboard/static/src/pages/projects/list.tsx` 任务进度列 render：按 `record.progress_phase` 分支——`"verify"` 时 `strokeColor="#52c41a"`、percent 取 `pct(verify_done, verify_total)`、文案 `verify_done/verify_total` + `verify_current` 辅助文案（非空才渲染）、run 线索不渲染；`"impl"` 分支维持现状 JSX 与数据源完全不变
- [x] 3.2 列 sorter 按 phase 切换排序键：每行取 `phase === "verify" ? pct(verify_done, verify_total) : pct(task_done, task_total)` 后比较

## 4. 构建与真实数据验证

- [x] 4.1 前端构建通过无编译错误（dist 由框架 merge 后自动重建，不提交产物）；testid `task-progress-cell` 在 impl 分支保留
- [x] 4.2 离线调 `spec_summary` 核对存量数据：full 模式 testing SPEC（如有）verify 阶段字段齐全、done/pushed SPEC（如 add-cost-observability）phase=impl、fast-track SPEC（task-track 等）恒 impl；类型定义 `SpecSummary`（services/dashboard.ts）同步补 `progress_phase`/`verify_current` 字段
