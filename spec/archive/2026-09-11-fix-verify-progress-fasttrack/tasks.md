## Deliverables

```yaml
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: tests/test_dashboard_data.py
  kind: modify
```

## 1. 测试先行（TDD 红）

- [x] 1.1 `tests/test_dashboard_data.py` 新增用例：fast-track SPEC 无进度文件、专属副本 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 含 `verification.scenarios`（如 8 条全 `pass`）→ `parse_verify_progress` 返回 `exists: True`、`total: 8`、`done: 8`、`current` 为「验证完成: 8通过, 0失败, 0错误」、`source: "run-result"`（预期先失败）
- [x] 1.2 新增计数口径用例：场景 status 混合 `pass`/`fail`/`failed`/`error`/`warning`/`exempt` → 通过/失败/错误三桶按 design 口径归类（`fail` 与 `failed` 同计失败、`warning`/`exempt` 不入三桶但计入 total）
- [x] 1.3 新增优先级与守卫用例：进度文件存在时优先返回文件值不回退（补 `source: "file"` 断言）；双缺省返回 `exists: False`；主树共享文件携带 spec 与当前不符时忽略

## 2. 数据层回退合成（TDD 绿）

- [x] 2.1 `core/dashboard/data.py` 的 `parse_verify_progress`：进度文件缺失时调用 `parse_run_result_scenarios` 取场景列表，按口径合成 `total`/`done`/`current`/`source`；场景为空时维持 `exists: False` 返回，不抛异常
- [x] 2.2 跑通 1.1-1.3 新用例及 `tests/test_dashboard_data.py` 既有全部用例（full 模式优先级零回归）

## 3. 列表展示兜底

- [x] 3.1 `core/dashboard/static/src/pages/projects/list.tsx` 验证列：`verify_total === 0` 时渲染纯文本 `—`（不包 Popover）；`verify_total > 0` 时维持 `done/total` + 既有 Popover 渲染不变

## 4. 真实数据离线验证

- [x] 4.1 用存量 fast-track SPEC 真实专属副本（task-track 11 场景、fix-verify-verdict-visibility 8 场景、add-done-duration-persist 6 场景等）离线调 `parse_verify_progress`，确认返回 N/N 与终态文案、full 模式 spec（add-cost-observability）走进度文件路径不回退
- [x] 4.2 前端构建通过（dist 由框架 merge 后自动重建，本次仅验证构建无编译错误），列表验证列 fast-track 行显示 N/N、无数据行显示 `—`
