# Proposal: task-track — tasks.md 任务清单跟踪链路治理

## Why

2026-09-04 诊断发现：planner/需求 Agent 生成 tasks.md 时分组标题漂移（旧格式 `## 1. 标题` → 新格式 `## 1 标题`，编号后无点号），而 CLI（`.fenix/bin/fenix_process.py`）与 dashboard 后端（`core/dashboard/data.py`）的分组解析正则 `^##\s+\d+\.\s+` 要求点号，导致任务清单在 `/fenix-process` 输出与 dashboard v3 spec 详情页**整块静默消失**（`groups=[]` → `if groups:` 跳过，无任何报错）。run-lifecycle-hardening（17/17 已完成）受影响，已在当日热修正则（点号可选），但三处根因未除：

1. **写入端无格式契约**：`fenix_spec.py` 的 tasks instructions 模板仅在示例中暗示 `## 1. ` 格式，guideline 只说 "numbered headings"，约束力为零，格式随轮次漂移必然复发（且可能漂移出正则无法兼容的第三变体，如无编号标题）。
2. **晋升无机械拦截**：drafted→ready 晋升 lint 只校验 Deliverables 声明形态，不校验 tasks.md 可解析性——不可解析的 tasks.md 照常晋升，直到 run 结束才发现进度不可跟踪。
3. **解析端静默跳过**：解析失败时 CLI/dashboard 均无可见提示，用户看到的「没有任务清单」与「确实没有任务」无法区分——假阴性放大器。

## What Changes

- **写入端格式固化**：`.fenix/bin/fenix_spec.py` 的 tasks artifact instruction/template 中，将分组标题格式升级为 MUST 约定：`## <编号>. <标题>`（编号为阿拉伯数字，编号后必须带点号），并注明下游解析器与晋升 lint 依赖此格式。
- **晋升 lint 拦截**：新增 tasks.md 可解析性校验——tasks.md 存在但按下游解析同款规则解析出 0 个任务分组时，drafted→ready 晋升被拒绝（保持 drafted + 写 STATE error，错误消息含「tasks.md」字样），沿用既有晋升 lint 的 fail-open 语义。
- **解析端显式提示**：
  - CLI：`fenix_process.py` 在 tasks.md 存在但解析出 0 分组时打印可见警告（`⚠ tasks.md 存在但未解析出任务…`），不再静默跳过。
  - dashboard 后端：spec 详情组装新增 `tasks_note` 字段（tasks.md 存在但 `parse_tasks` 返回空时给出提示文本，否则为 None）。
  - dashboard 前端：v3 spec 详情页任务清单 Card 空态区分两种情况——有 `tasks_note` 时显示 warning 级提示，无 tasks.md 文件时保持「暂无任务清单」。
- 兼容性保留：解析正则维持点号可选（`## 1. 标题` 与 `## 1 标题` 两种历史格式均可解析），本次不迁移存量文件。

## Capabilities

### New Capabilities

- `tasks-md-tracking`：tasks.md 任务清单的格式契约（写入端约定）、可解析性晋升拦截（lint）、解析失败显式提示（CLI + dashboard）三层治理。

### Modified Capabilities

（无——活跃 `openspec/specs/` 为空；归档能力 `native-spec-generation` 仅约束模板存在性，未固化模板文本内容，不受影响。）

## Impact

- **代码**：`.fenix/bin/fenix_spec.py`（模板文本）、`core/deliverables.py`（新增 lint）、`core/pm_engine/engine.py`（晋升 lint 并列调用）、`.fenix/bin/fenix_process.py`（CLI 警告）、`core/dashboard/data.py`（`tasks_note` 字段）、`core/dashboard/static/src/pages/projects/detail.tsx`（空态提示分支）。
- **产物**：`core/dashboard/static/dist/` 需重建并提交（v3 入库产物，否则 UI 验证假阴性）。
- **部署**：`data.py` 变更需重启 dashboard(:8787) 生效（既有惯例）。
- **风险**：晋升 lint 误拦存量 spec——lint 判定必须与下游解析正则严格同源（点号可选双格式），对全部既有 spec 的 tasks.md 回归验证 0 误拦。
