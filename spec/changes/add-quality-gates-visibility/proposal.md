# add-quality-gates-visibility 提案

## Why

implementer 勾选完 tasks.md 全部任务后，还要过大量检查/门禁（全量回归、前端 build+tsc、ocr 代码审查、交互契约自查、结果文件产物硬门、交付物守卫+relint），实测占成功 run 时长的 67%（标准样本 20.8/31 分钟），门禁打回循环更可连续烧掉数小时（72.5 分钟 5 轮 run 中 4 轮被打回）。这些环节目前在 Dashboard 上完全不可见——用户只能看到一个 `gate-blocked` 红点与截断归因，无法知道「卡在哪道门、过了几道、还剩几道」，观察与排障都只能翻 run 转录。

## What Changes

- **新增质量门禁落盘契约**：implementer 在收尾检查阶段逐项完成后，将 run 内自查 3 项（全量回归 / 前端 build+tsc / 交互契约自查）的结果渐进写入 `.fenix/verify-progress/<spec>/quality-gates.json`（每项完成即更新，非收工一次性写）；随既有 verify-progress 拷回机制落主树。**ocr 代码审查不在 run 内自查之列**——它由 `add-impl-ocr-parallel-lane` 交付的框架侧异步车道在 testing 窗口执行，实现者 run 不再包含该环节。
- **Dashboard 读侧合成**：新增解析函数读取 quality-gates.json（run 内 3 项）并与框架判定合成统一的 6 道门禁状态列表——ocr 门（`code-review`）从 ocr 车道产物 `.fenix/verify-progress/<spec>/code-review.json` 读侧合成（车道在飞→running、completed→passed、unavailable→skipped），产物硬门取 run 终态、交付物守卫取 STATE 状态；历史 spec / 缺数据项 fail-open 显示「无记录」，不抛异常。
- **spec 详情页新增「质量门禁」Card**：位于任务清单 Card 之下，以与任务清单一致的勾选列表形式（Checkbox + 删除线）展示 6 道门禁的通过状态，附进度条从零走（复用 `ProgressBarTile`，门禁专属配色）。
- **列表页进度条扩展 gates 阶段**：`progress_phase` 新增 `"gates"` 枚举，触发窗口两支——implementing 且任务全勾、收尾门禁进行中（收尾自查 3 项落盘）；testing 且 ocr 车道 running（ocr 并行审查进行中）。主进度条以门禁专属颜色从零走门禁完成度；阶段判定单点在后端 summary 层，前端纯渲染。
- 不改动任何门禁的判定逻辑本身（不新增/删除/放宽门禁），纯可观测性读侧 + 落盘增强。
- **依赖顺序**：本 SPEC MUST 在 `add-impl-ocr-parallel-lane` 合入主树后再激活（两者均为手工激活）——先激活本 SPEC 会按旧内联形态实现 ocr 门数据源，并行车道合入后需二次返工。

## Capabilities

### New Capabilities

- `quality-gates-progress`: 质量门禁进展的可观测性契约——quality-gates.json 落盘格式（run 内自查 3 项）与渐进更新时机、ocr 门从框架异步车道产物的读侧合成规则、6 道门禁的状态语义（passed/failed/running/pending/skipped/unknown）、Dashboard 读侧合成规则（fail-open）、详情页「质量门禁」Card 的勾选列表与进度条渲染。

### Modified Capabilities

- `task-progress-phase-display`: 列表「任务进度」列的阶段判定新增 `"gates"` 枚举值与门禁专属颜色的门禁进度渲染（impl 蓝 → gates 橙 → verify 绿），判定单点仍在后端 `spec_summary`。

## Impact

- **写侧（落盘契约）**：`core/agent_runner/prompt_builder.py`（implementer 收尾检查段注入 quality-gates.json 写入要求）、`agents/implementer.md`（本期不改：gates 契约经 prompt 注入动态下发，静态模板不含 gates 内容）、`core/agent_runner/result_gate.py`（对账 quality_gates 声明，缺失 fail-open 不新增死循环门）。
- **读侧（Dashboard 数据层）**：`core/dashboard/data/`（新解析函数 + `spec_summary`/`spec_detail` 字段下发 + `progress_phase` 判定扩展 + 门面 re-export 登记 D8 缝）。
- **前端**：`core/dashboard/static/src/services/dashboard.ts`（类型）、`pages/projects/detail.tsx`（质量门禁 Card）、`pages/projects/list.tsx`（gates 阶段渲染）；改完须 `npm run build` 重建 dist。
- **测试**：`tests/test_dashboard_data.py` 等后端数据层用例、前端 node:test 用例。
- **风险面**：落盘写入与结果文件对账的契约不一致是历史高发事故区（impl-code-review-gate 键名契约缺口等），新契约必须键名固化 + 守卫侧宽松对账（fail-open），避免制造新的打回循环。
