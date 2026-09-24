# add-code-fix-startup-stage-visibility 任务

## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/CodeFixProgressCard.tsx
  kind: modify
- path: tests/test_code_fix_startup_stage_visibility.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 读侧合成：startup_stage 推断

- [ ] 1.1 `core/code_fix.py` 新增 `_synthesize_startup_stage(project_root, progress)` 并接入 `read_progress`：激活条件 `running=true 且 phase ∈ {fixing, retrying} 且 out 零有效行`（与 `_synthesize_item_progress` 激活域互补，out 有行时短路置 null，复用其已读行集合不重复 IO）；以 `progress.run_id` 定位主树 `.fenix/runs/<run_id>.jsonl`，末行按尾部截断读取（如只读末 4KB，MUST NOT 全量 read_text——verbose 流转录可达 MB 级），末行事件 `type` 映射阶段短语——文件缺失→「等待 agent 进程启动」；`system` init/hook_started/hook_response→「会话初始化中」；`system` 其余子类型（task_started/task_progress/background_tasks_changed 等 mid-run 遥测）→「agent 启动处理中」；`assistant` thinking/text→「模型分析分组中」；`assistant` tool_use→「正在执行 <工具名>」；其他/未知→「agent 启动处理中」；时长=当前时间−转录文件 birth time（转录为懒创建：首条流事件经 append_run_line 才建文件，birth=首事件到达时刻、非 spawn 时刻，spawn→首事件窗口由文件缺失分支覆盖；stat 取不到 birth 时 waited_minutes=null，文件缺失时同样 null）。字段形态 `null | {"stage": str, "waited_minutes": int|null}`（恒带键），写入返回 dict 顶层键 `startup_stage`。容错硬要求：文件缺失/读取异常/末行非 JSON/无 type 键 → 置 null，任何分支不得抛异常中断 `read_progress`（读侧 MUST NOT 500 既有口径）；`startup_stage` 进 FIX_PROGRESS_DEFAULT（缺省 null，对齐 item_done/current_item 先例与「新键 MUST 进缺省集」既有约定），合成函数无条件先置 null，`write_progress` 剥离该键不落盘（对齐 core/code_fix.py:170-174 先例，防合成快照经合并写落盘成陈旧状态）

- [ ] 1.2 `read_progress` 返回值全链路复核：`_synthesize_startup_stage` 置 null 的路径（running 非 true / phase 不在激活域 / out 有行 / 解析失败）逐条确认 `startup_stage` 键恒在场且为 null，不出现「键缺失」形态（对齐 `_synthesize_item_progress` 的 null 三态先例，data 层转导只 pop worktree/run_id、合成字段自然透出，`core/dashboard/data/code_review.py` 预期零改动——若复核发现必须改动，改动最小化并在提交信息注明原因）；并复核 `write_progress` 合并写后进度文件不含 `startup_stage` 键（剥离生效，合成快照不落盘）

## 2. 前端渲染：准备段

- [ ] 2.1 `core/dashboard/static/src/services/dashboard.ts` `CodeReviewFixProgress` 类型增补 `startup_stage` 可空字段（`null | { stage: string; waited_minutes: number | null }`）
- [ ] 2.2 `CodeFixProgressCard.tsx`：`item_done=null 且 startup_stage 非空` 时在原「本批已处置」行位置渲染准备段（阶段短语 + 「已等待 N 分钟」，waited_minutes 为 null 时只显示阶段短语）；`item_done=null 且 startup_stage 为 null` 维持既有整段不渲染口径（不回退 2026-09-23 决定）；`item_done` 有值时段逻辑完全不进入（条级计数优先）
- [ ] 2.3 `npm run build` 通过（dist 为构建产物，reference）

## 3. 测试与收尾

- [ ] 3.1 新增 `tests/test_code_fix_startup_stage_visibility.py`：覆盖激活域四分支（fixing+零行激活 / retrying+零行激活 / out 有行短路 null / running 非 true 置 null）；末行映射五形态（system→会话初始化中、assistant thinking/text→模型分析分组中、assistant tool_use→正在执行 <工具名>、文件缺失→等待 agent 进程启动、末行非 JSON→null）+ birth time 缺失退化 waited_minutes=null + system 遥测子类型（task_started）→「agent 启动处理中」+ write_progress 剥离断言（合成值不落盘）+ 全程不抛异常；tmp_path 构造夹具不触真实 `.fenix/`（对齐「用户级配置敏感测试」教训）；旧用例 `tests/test_code_fix.py`、`tests/test_code_fix_item_level_progress.py` 全绿（startup_stage 新键不破坏既有断言）
