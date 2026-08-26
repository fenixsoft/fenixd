# Proposal: add-task-progress-sync

## Why

实现 Agent 用会话内 TaskCreate/TaskUpdate 汇报任务完成，但经常不按 prompt 第 6 步要求回写 `tasks.md` 勾选（LLM 对收尾杂务服从率低 + worktree 隔离下勾选易随未提交目录丢失）。结果：多个 SPEC 已 pushed 但任务进度显示 0%（如 fix-add-multi-project-monitoring 0/4、fix-fix-fix-worktree-spec-seeding 0/3），Dashboard 只能用读侧实时叠加（`_parse_run_task_done`）事后圆谎，且 run 文件清理后叠加失效、进度永久失真。进度数据应从写侧确定性保证，而非依赖 LLM 自觉。

## What Changes

- **daemon 写侧回写**：implementer run 终态为 success 时，PM Engine 解析该 run 产物的 TaskCreate/TaskUpdate 完成集合（复用 `data._parse_run_task_done` 的解析语义），把主树 `openspec/changes/<spec>/tasks.md` 中对应 id 的 `- [ ]` 确定性改为 `- [x]`，并 commit。幂等：已勾选跳过；agent 已自己勾选的不重复操作。
- **verified→done 一致性门禁**：SPEC 进入 verified→done 转换时校验 tasks.md 完成度与 run 记录声明一致——`.fenix-run-result.json` 声明 success 但存在「未勾选且不在 done_ids」的任务时，阻断自动推送并在 error 字段暴露缺口（人工裁决），不再静默放行。
- **读侧叠加保留为兜底**：`_should_overlay` 实时叠加逻辑不变，作为 implementing 期间的实时视图；写侧回写落地后 done/pushed 状态不再依赖它。

## Capabilities

### New Capabilities
- `task-progress-sync`: implementer run 结束后 daemon 从 run 产物确定性回写主树 tasks.md 勾选，以及 verified→done 阶段的任务完成一致性门禁。

### Modified Capabilities

## Impact

- **代码**：`core/pm_engine.py`（run 终态处理处新增回写调用 + `_on_spec_verified` 新增门禁）、`core/dashboard/data.py`（`_parse_run_task_done` 提升为可复用解析函数）
- **行为**：pushed SPEC 的 tasks.md 进度为 100% 或在 error 字段明确记录未完成任务清单；修复型 SPEC（fix-*）同样适用
- **风险**：回写 commit 会出现在 git log 中，需用固定 message 标识（如 `[fenix] <spec>: sync task progress from run record`）以便区分 agent 提交
