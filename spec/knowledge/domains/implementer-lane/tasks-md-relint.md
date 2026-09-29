<!-- knowledge: capability=tasks-md-relint rev=1 sources=spec/archive/2026-09-17-add-tasksmd-relint-gate -->

# tasks.md 重 lint 门

tasks.md 可解析性 lint 在实现收口期的复检门禁——implementer 中途编辑 tasks.md（收尾勾选）后，merge 前以实现分支/worktree 上的最终版本复检，损伤形态不放行。

## 现行规则

- lint 违规形态（`lint_tasks_parseable`）：
  - 0 分组：tasks.md 存在但分组标题全部不匹配 `^##\s+\d+\.?\s+` → 违规，不因任务行存在而放行；
  - 分组在但任务行为 0：分组数 ≥1 时还须校验任务行总数——匹配 `^- \[(x| )\]` checkbox 前缀的任务行总数为 0 → 违规；
  - 违规文案含「tasks.md」「任务分组」字样与修正处方：任务行行首必须为 `- [ ]` / `- [x]` 形态，点名 `^-` 损伤特征。
- 放行形态：tasks.md 不存在 → lint 返回空（fast-track 前置 SPEC 允许后补）；分组与任务行均可解析 → 返回空。
- full 车道复检挂点：implementer run 成功且通过零变更哨后、merge 之前，以**实现分支 HEAD** 的 `spec/changes/<name>/tasks.md` 为基准复检；违规时 MUST NOT 合并、MUST NOT 推进状态，按失败重派，error 写明违规明细与修正处方。
- fast-track 车道复检挂点：成功流程在交付物守卫之后、硬校验之前，以 **worktree 内** tasks.md 为基准复检；违规走失败处置（不合并、保留 worktree、按失败重派），error 写明违规明细与修正处方。
- fail-open：复检执行路径上的任何异常——lint 函数抛错、`git show <branch>:<path>` 非零退出或超时——记 WARNING（含 spec 名与异常摘要）后放行，不阻断成功收口。

## 溯源

- [2026-09-17 2026-09-17-add-tasksmd-relint-gate](spec/archive/2026-09-17-add-tasksmd-relint-gate/) — 「分组在但任务行为 0」新增为违规形态（与既有 0 分组并列）；full/fast-track 两车道收口期 merge 前复检门禁与 fail-open 语义落地
