# Design: Fix Implementer Task Progress

## Context

进度可见性断链的完整因果（均已从实现代码与 in-flight run 产物验证）：

```
tasks.md 27 项 ──prompt 无粒度约束──▶ agent 归并为 6 个分组级 TaskCreate（无编号 subject）
                                         │
   parse_run_task_done ── _TASK_ID_RE 提取 subject 内嵌 "Task 1.1" ──▶ done_ids = ∅
                                         │
                ┌────────────────────────┴────────────────────────┐
                ▼                                                    ▼
   dashboard 叠加(data.parse_tasks live)                     写侧回写(_sync_task_progress)
   → 快照 0 勾选 / 假进度                                        → done_ids 空: 直接跳过
```

关键事实：**两套现有机制都依赖同一假设「TaskCreate subject 内嵌 tasks.md 编号」**，而这个假设从未被提示词保障过。`flat_done`（harness 创建序完成下标）在 run 产物中一直存在且不依赖编号，是零成本兜底资源。

## Goals / Non-Goals

**Goals:**
- 消灭「spec 正常实现但进度永远 0/N」的盲态，Dashboard 能区分卡死与推进。
- 从源头让 harness TaskCreate/Update 行为与 tasks.md 编号对齐（subject 契约）。
- 回写兜底：即便 subject 编号契约失效（存量/不规则 run），收尾仍能把完成状态落盘 tasks.md。
- 展示兜底：tasks.md 快照与 run 实时完成度并行显示，互不掩盖。

**Non-Goals:**
- 不做 run 中途（终态前）的增量回写（watcher 侧同步）——留待后续，fast-track 仅终态回写。
- 不做 subject 文本相似度对齐（difflib，方案 C）——契约化后无需；复杂度不匹配 fast-track。
- 不改 harness / Claude Code 本身（TaskUpdate 语义官方固定）。
- 不改变 STATE.md / run 产物格式。

## Decisions

### D1 提示词契约段（implementer-task-protocol）

在 `prompt_builder.py` implementer 分支插入强制段（位于第 6 步勾选之前），内容：

```
## 任务进度契约（task-progress-contract，强制）
- 每一条 tasks.md 任务（如 "1.3 配置解析签名缓存"）只能由一个 TaskCreate 对应，
  TaskCreate 的 subject MUST 以 "Task <id>: <标题>" 开头，id 直取 tasks.md 的
  "分组号.任务号"（如 "Task 1.3: 配置解析签名缓存"），禁止把多条任务归并为一条
  TaskCreate，也禁止把分组（## 标题）当任务创建。
- 开始实现某任务时创建其 TaskCreate；该任务完成的瞬间立刻对同一 taskId 发
  TaskUpdate status=completed，不得攒批到收尾。
- 收尾时逐项 Edit tasks.md，把每条已完成任务 `- [ ]` 改为 `- [x]`，
  与全部 TaskCreate/TaskUpdate 记录一一对应，不留半勾。
```

- 粒度关系：**一个 tasks.md 任务 = 一个 TaskCreate = 一次完成汇报 = 一次勾选**，四者对齐后侧写叠加、写侧回写、展示三端全部自动工作。
- full 与 fast-track implementer 分支都加（两分支入口不同，均在 build_implementer_prompt 内部分支处理）。
- 提示词变更对进行中 run 无扰动（prompt 在派发时构建）。

### D2 回写兜底（task-progress-writeback）

`engine.py._sync_task_progress`（现状：`done_ids` 空 → 直接 return）改为三级回退：

1. `done_ids` 非空 → 现状精确对齐（不变）。
2. `done_ids` 空但 `flat_done` 非空 → **按创建序回退**：取 tasks.md 扁平任务序列（按文件顺序），把前 `max(flat_done)+1` 个未完成项勾选。理由：契约化后 agent 按文件序创建任务，flat 下标序与 tasks.md 文件序同构；粒度退化但方向正确（宁多勾不勾错——max 保证所有已汇报完成的任务都被覆盖）。
3. 两者皆空 → 保持跳过（不误写）。

风险：flat 回退在 agent 创建顺序与文件序不一致时会错勾。缓解：flat 回退仅当 `created_count >= tasks.md 未完成项数的一半` 时启用（弱一致性校验），否则跳过留待管理。工作树不干净跳过逻辑保持。

### D3 run 层进度可见性（run-progress-observability）

- `data.py`：新增 `run_task_progress(proot, spec_name) -> {"done": int, "total": int}`——用 `parse_run_task_done` 的既有输出（`created_count`, `len(completed_idx)`），**不依赖 tasks.md 编号**（这正是它作为兜底的资本）。
- `spec_summary` 增加字段 `run_progress`；`run_progress.done` = completed TaskCreate 数，`total` = created_count（无 run 时为 `{done:0,total:0}`）。
- 前端：任务进度列展示「tasks.md done/total」；当 `spec_summary.run_progress.done > tasks.md 快照 done` 时叠加显示 run 完成线索（如 `2/6 任务完成 · run 进行中`）。最小改动：仅表格列 + 详情页统计卡片，不重做布局。

## Risks / Trade-offs

- **契约不遵守**：提示词是软约束，后续 run 仍可能归并。兜底 D2.2 + D3 保证不会回到「全盲态」，但精确对齐依赖纪律。缓解：验收标准要求实测运行一轮 implementer run 验证 subject 编号格式。
- **flat 回退错勾**：弱一致性校验（D2.2 启用条件）拦截明显不匹配场景；最坏情况多勾 1-2 项，可经 tasks.md 手工修正，成本远低于全盲。
- **前端字段新增**：`run_progress` 为增量字段，向后兼容（旧前端忽略未知字段）。
- 当前 in-flight 的 `add-dashboard-incremental-data` run 将按旧协议执行，但**多不出错**——它结束时若 done_ids 空且 flat 有值，D2.2 会补勾一次（可接受），其 dashboard 展示由 D3 字段立即受益。