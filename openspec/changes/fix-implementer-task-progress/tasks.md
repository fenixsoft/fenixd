# Tasks

## Deliverables

（修订：v3 前端实际位于 core/dashboard/static/{src,dist}，原 v3/ 目录声明与仓库布局不符，
且目录型声明触发交付物守卫 blob 校验死锁——按 remove-auto-run-cleanup 先例改文件路径）

```yaml
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: modify
- path: tests/test_task_progress_protocol.py
  kind: new
```

## 1. implementer 任务编号契约（implementer-task-protocol）

- [x] 1.1 prompt_builder.py implementer 分支（agent_type == "implementer"）注入「任务进度契约」强制段：TaskCreate subject 前缀 `Task <分组号.任务号>: <标题>`；一任务一 TaskCreate 禁止归并；完成瞬间 TaskUpdate completed 不得攒批；收尾逐项勾选 tasks.md 与 TaskUpdate 一一对应
- [x] 1.2 fast-track implementer 分支（第 480 行附近）注入同一契约段（文本复用，独立构建路径各自断言）
- [x] 1.3 测试 tests/test_task_progress_protocol.py：双分支 prompt 均含契约段；契约文本断言 subject 示例格式

## 2. 写侧回写兜底（task-progress-writeback）

- [x] 2.1 engine.py `_sync_task_progress` 改造为三级回退：done_ids 优先；空则 flat_done + 弱一致性校验（created_count ≥ tasks.md 未完成项数一半）按创建序勾前 max(flat_done)+1 个；皆空跳过
- [x] 2.2 flat 回退的 tasks.md 修改走既有原子写路径（临时文件 + replace），异常仍非阻塞
- [x] 2.3 测试：无编号 run 兜底勾选、弱校验不符跳过、done_ids 精确路径零回归（构造 run 产物 fixture）

## 3. run 层进度可见性（run-progress-observability）

- [ ] 3.1 data.py 新增 `run_task_progress(proot, spec_name)`：复用 parse_run_task_done 输出返回 {done,total}，无 run/解析失败时 {0,0}
- [ ] 3.2 `spec_summary` 增加 `run_progress` 字段（含 /api/specs 传播）
- [ ] 3.3 前端任务进度展示：tasks.md 快照主刻度 + run_progress.done > 快照 done 时叠加 run 完成线索（表格列 + 详情统计卡片）
- [ ] 3.4 重建 dist 并提交（core/dashboard/static/v3/dist/）
- [ ] 3.5 测试：run_progress 字段存在性与计数断言；无 run 缺省 {0,0}

## 4. 端到端验证

- [ ] 4.1 全量测试回归（tests/ dashboard + pm_engine 相关，既有用例零回归）
- [ ] 4.2 实测：派发一轮新 implementer run（可用现成 in-flight 之后的新 spec 或一次性测试 spec），断言 TaskCreate subject 前缀合规、TaskUpdate 细粒度、收尾 tasks.md 勾选与 run 完成一致
- [ ] 4.3 Dashboard 实测：浏览器确认任务进度列在 run 进行中能显示推进（run 线索），不再静止 0/N
- [ ] 4.4 验证 add-dashboard-incremental-data（in-flight）结束时补勾行为符合 D2.2 弱校验预期