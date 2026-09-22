# add-quality-gates-visibility 设计

## Context

implementer 勾选完 tasks.md 全部任务后，到 merge 前还要过 6 道检查/门禁（实测占成功 run 时长 67%，打回循环可连续烧数小时），Dashboard 上除 `gate-blocked` 红点外完全不可见。既有可复用机制：

- **verify-progress 范式**：验证引擎逐场景原子写 `.fenix/verify-progress/<spec>.json`，dashboard 只读解析 + fail-open；ocr 审查产物已落 `.fenix/verify-progress/<spec>/code-review.json`（同目录），run 结束时 runner 既有逻辑整体拷回主树（`core/agent_runner/runner.py` verify-progress 拷回段）。
- **task-progress-phase-display**：列表进度条按后端单点判定的 `progress_phase` 换源换色（impl 蓝/verify 绿/出题青）。
- **worktree 优先先例**：`core/dashboard/data/tasks.py` 在 implementing 态优先读 worktree 内 tasks.md（run 进行中即可见）。

## Goals / Non-Goals

**Goals:**

- 6 道门禁（全量回归 / 前端构建+tsc / ocr 代码审查 / 交互契约自查 / 结果文件产物硬门 / 交付物守卫+relint）的状态在详情页以任务清单同款勾选列表 + 从零走的进度条可见。
- 列表页主进度条新增 gates（橙）阶段，任务全勾、门禁进行中时从零走门禁完成度。
- run 进行中即可见渐进进展（收尾检查每完成一项即落盘）。
- 历史 spec / 缺数据全部 fail-open，零新增打回循环。

**Non-Goals:**

- 不改动任何门禁的判定逻辑（不新增/删除/放宽门禁，不改重试预算）。
- 不做门禁耗时统计（需解析 run 转录，另行立项）。
- 不动验证链三阶段（出题/验证/judge）的既有展示。
- 不为框架守卫 2 项引入框架侧写文件（读侧合成即可，见决策 4）。

## Decisions

1. **落盘文件与 runner 零改动**：`quality-gates.json` 放 `.fenix/verify-progress/<spec>/` 目录（与 `code-review.json` 并列），随 runner 既有目录拷回机制落主树。备选「写 `.fenix-run-result.json` 新节」被否：结果文件是收工一次性写，无法渐进可见，且混入守卫刚性对账面。
2. **渐进更新而非收工一次性写**：prompt 注入段要求每完成一项检查即重写该 JSON（全量重写小文件，无并发写者——implementer 单线程收尾）。这是用户核心诉求（ocr 一跑十几分钟，要看到「进行中」）。
3. **守卫宽松对账（fail-open）**：`result_gate` 对 quality-gates.json 只做「存在则查格式」的合法性检查，违规仅 WARNING；缺失零拦截。理由：落盘是软约束，若设硬门则 implementer 漏写即打回重烧——正是本 spec 要治理的摩擦模式（impl-code-review-gate 键名契约缺口教训）。键名在 spec 中逐字固化。
4. **框架 2 项由读侧合成、不落盘**：产物硬门的权威判定已在 run 终态（gate-blocked/success），交付物守卫的权威判定已在 STATE 状态——读侧从既有数据源推导，避免框架进程新增写者引入竞态。run 内 4 项以落盘为权威，两组不交叉覆盖。
5. **worktree 优先读取**：implementing 且 worktree 存在时优先读 worktree 内文件（复用 tasks.py 既有解析与先例），使 run 进行中即可见；run 结束后读主树拷回版本，时序无缝衔接。
6. **`progress_phase` 扩展 gates 枚举**：判定单点留在 `spec_summary`（既有约定），条件 = implementing ∧ 任务全勾 ∧ 门禁可见 ∧ 未全了结；全了结回退 impl（不滞留满格橙条）。门禁数据完全不可见（exists=false）不进 gates 阶段，避免历史 spec 列表闪烁新颜色。
7. **skipped 计入 done**：`total` 恒 6，`done = passed + skipped`（skipped 是「已了结」而非「未做」），进度条可走满。`unknown`/`pending`/`failed`/`running` 均不计入。
8. **门禁专属配色**：橙 `#fa8c16` + 淡橙底轨（对齐 verify 绿 `#52c41a` + 淡绿底轨的做法），与 impl 蓝/verify 绿/出题青四色互斥。详情页 Card 内 `ProgressBarTile` 以参数化单色变体复用（现有控件渐变色写死，需加可选 `strokeColor` 参数）。
9. **新数据层模块**：解析与合成函数放 `core/dashboard/data/quality_gates.py`（新文件），`__init__.py` 登记 re-export 与 D8 patch 缝；`summary.py` 仅消费。避免 spec_docs.py 继续膨胀。

## Risks / Trade-offs

- [implementer 漏写/写坏 quality-gates.json → UI 缺数据] → fail-open 显示 unknown；prompt 注入含逐字 schema；守卫 WARNING 留观测痕迹。接受「偶尔缺数据」换「零新增打回」。
- [键名漂移复发（同义改写 gate-id/status）] → spec 逐字固化键名 + 前端按未知 gate-id 容错渲染（不崩、显示原始 id）。
- [worktree 路径推导在 resume/重建场景失效] → 复用 tasks.py 既有解析；解析失败静默回退主树版本，最坏退化为「run 结束后才可见」。
- [gates 阶段误判（重试轮、fast-track 瞬时连转）] → 判定条件纯机械且单点函数化，边界 Scenario 全覆盖（未全勾/全了结/exists=false/fast-track）。
- [详情页 SSE 全量 detail 推送字段增大] → 6 项门禁数据量级极小（<1KB），无性能顾虑。
- [dist 时序] → dist 由框架 merge 后自动重建、不提交产物（既有约定）；任务侧仅要求 worktree 内 `npm run build` 通过。

## Migration Plan

- 纯增量上线：无 schema/数据迁移，历史 spec 读侧自然 fail-open（unknown/不进 gates 阶段）。
- 部署顺序：后端与 prompt 随 daemon 重启生效；前端 `npm run build` 重建 dist 后生效。新旧两端短暂错配时（新后端旧前端）多出的字段被前端忽略，无害。
- 回滚：移除读侧字段与前端分支即回退；已落盘的 quality-gates.json 残留无害（无消费者）。

## Open Questions

无——门禁范围（全链 6 道）、数据路线（结构化落盘）、执行模式（full）、执行时机（手工激活）均已由用户确认。
