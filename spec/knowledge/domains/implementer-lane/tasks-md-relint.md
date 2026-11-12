<!-- knowledge: capability=tasks-md-relint rev=2 sources=spec/archive/2026-09-17-add-tasksmd-relint-gate -->

# tasks.md 重 lint 门

tasks.md 可解析性 lint 在实现收口期的复检门禁——implementer 中途编辑 tasks.md（收尾勾选）后，merge 前以实现分支/worktree 上的最终版本复检，损伤形态不放行。

## 现行规则

- lint 违规形态（`lint_tasks_parseable`）：
  - 0 分组：tasks.md 存在但分组标题全部不匹配 `^##\s+\d+\.?\s+` → 违规，不因任务行存在而放行；
  - 分组在但任务行为 0：分组数 ≥1 时还须校验任务行总数——匹配 `^- \[(x| )\]` checkbox 前缀的任务行总数为 0 → 违规；
  - 分组与任务行在但缺编号（2026-11-12 新增）：编号分组之内存在匹配 checkbox 前缀但不匹配任务 id 语法的任务行 → 违规——id 语法单源复用 `core/run_task_track.py` 的 `_TASK_ID_PATTERN`（`\d+\.\d+[a-z]?`，字母后缀合法）；任何层级非分组标题（H1 文件题、H2/H3 Deliverables、Acceptance、验证修复等装饰小节）退出分组语境，其后的无编号勾选清单（存量惯例）不拦；
  - 违规文案含「tasks.md」「任务分组」字样与修正处方：任务行行首必须为 `- [ ]` / `- [x]` 形态，点名 `^-` 损伤特征；缺编号形态点名缺编号行数与首见行号，处方为逐条补「组号.序号」编号。
- 为什么缺编号必须拦：dashboard 展示解析器（`core/dashboard/data/tasks.py` 严格版 `^- \[(x| )\] (\d+\.\d+) (.+)$`）、完成度门（run_task_track）与 result_gate 产物对账全部按任务 id 识别任务——缺编号任务行被三方静默丢弃，任务清单显示为空而 lint 无感（宽松 checkbox 计数全命中）。
- 放行形态：tasks.md 不存在 → lint 返回空（fast-track 前置 SPEC 允许后补）；分组与任务行均可解析 → 返回空。
- full 车道复检挂点：implementer run 成功且通过零变更哨后、merge 之前，以**实现分支 HEAD** 的 `spec/changes/<name>/tasks.md` 为基准复检；违规时 MUST NOT 合并、MUST NOT 推进状态，按失败重派，error 写明违规明细与修正处方。
- fast-track 车道复检挂点：成功流程在交付物守卫之后、硬校验之前，以 **worktree 内** tasks.md 为基准复检；违规走失败处置（不合并、保留 worktree、按失败重派），error 写明违规明细与修正处方。
- fail-open：复检执行路径上的任何异常——lint 函数抛错、`git show <branch>:<path>` 非零退出或超时——记 WARNING（含 spec 名与异常摘要）后放行，不阻断成功收口。

## 溯源

- 2026-11-12 windows-native-support（事故，未立项） — 全文件 21 条任务行无编号（`- [ ] <描述>`），宽松计数放行、dashboard 任务清单为空；lint 新增「缺编号」违规形态堵住该类，id 语法经 f-string 复用 run_task_track 单源；`add-distill-run-work-summary` 同类潜伏实例（id 后直接接反引号无空格，严格解析器同样不认）一并被新判据覆盖，两者在 `TestExistingSpecsZeroMisfire` 登记为预期真阳性（文件保持事故原样作活体回归样本）
- 2026-09-17 2026-09-17-add-tasksmd-relint-gate（spec/archive/2026-09-17-add-tasksmd-relint-gate） — 「分组在但任务行为 0」新增为违规形态（与既有 0 分组并列）；full/fast-track 两车道收口期 merge 前复检门禁与 fail-open 语义落地
