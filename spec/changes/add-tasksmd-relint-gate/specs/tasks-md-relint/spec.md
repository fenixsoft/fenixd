# tasks-md-relint 能力规格

## ADDED Requirements

### Requirement: tasks.md 分组内任务行可解析性校验

`lint_tasks_parseable` 在「tasks.md 存在且分组数 ≥ 1」时，MUST 额外校验任务行总数：任务行（匹配 `^- \[(x| )\]` checkbox 前缀）总数为 0 时 MUST 返回违规；任务行总数 ≥ 1 时 MUST 放行。

#### Scenario: 分组存在但任务行全部带损伤前缀

- **WHEN** tasks.md 含 4 个合法分组标题（`## 1. 终态零提交门（TDD）` 形态），所有任务行均为 `^- [x] 1.1 …`（行首多 `^` 字符，checkbox 正则不匹配）
- **THEN** lint 返回恰好 1 条违规，文案同时含「tasks.md」「任务分组」与修正处方（必须为 `- [ ]` / `- [x]` 行首形态，点名 `^-` 损伤特征）

#### Scenario: 分组与任务行均正常

- **WHEN** tasks.md 含 ≥1 个合法分组、组内含 ≥1 行 `- [ ] 1.1 …` 或 `- [x] 1.1 …`
- **THEN** lint 返回空列表

#### Scenario: tasks.md 不存在

- **WHEN** spec 目录无 tasks.md
- **THEN** lint 返回空列表（放行，既有语义不变——fast-track 前置 spec 允许后补）

#### Scenario: 0 分组既有违规形态回归

- **WHEN** tasks.md 存在但分组标题全部不匹配 `^##\s+\d+\.?\s+` 正则（如 `## 标题` 无编号）
- **THEN** lint 返回违规（既有「0 分组」文案），不因任务行存在而放行

### Requirement: implementer 收口期 tasks.md 复检门禁（full 车道）

full 车道 implementer run 成功且通过零变更哨后、merge 之前，框架 MUST 以**实现分支 HEAD** 的 `spec/changes/<name>/tasks.md` 为基准运行 tasks.md 可解析性复检；违规时 MUST NOT 合并、MUST NOT 推进状态，按失败重派并在 error 中写明违规明细与修正处方。

#### Scenario: 分支上 tasks.md 带损伤前缀

- **WHEN** implementer 报成功、分支相对 main 有提交，但分支 HEAD 的 tasks.md 任务行全部为 `^- [x]` 损伤形态
- **THEN** 不执行 merge-back，spec 状态回 ready（或按车道既有失败语义），error 含 lint 违规明细与「行首应为 `- [ ]` / `- [x]`」修正处方，implementer 重新入队

#### Scenario: 分支上 tasks.md 正常

- **WHEN** 分支 HEAD 的 tasks.md 分组与任务行均可解析
- **THEN** 复检放行，流程进入交付物守卫与 merge，行为与既有完全一致

#### Scenario: 分支无 tasks.md（fast-track 前置 spec 后补形态）

- **WHEN** 实现分支上不存在 `spec/changes/<name>/tasks.md` 路径
- **THEN** 复检 fail-open 放行（与 lint「文件不存在不拦」语义一致）

#### Scenario: git show 读取失败

- **WHEN** `git show <branch>:<path>` 非零退出或超时（分支名异常等）
- **THEN** 复检 fail-open 放行并记 WARNING，不阻塞成功收口

### Requirement: implementer 收口期 tasks.md 复检门禁（fast-track 车道）

fast-track 车道成功流程在交付物守卫之后、硬校验之前，MUST 以 **worktree 内** `spec/changes/<name>/tasks.md` 为基准运行同一复检；违规时 MUST 走 `_handle_fast_track_failure`（不合并、保留 worktree、按失败重派），error 写明违规明细与修正处方。

#### Scenario: worktree 内 tasks.md 带损伤前缀

- **WHEN** fast-track run 报成功、结果文件 status 合法，worktree 内 tasks.md 任务行全部不可解析
- **THEN** 保留 worktree（`_keep_fast_track_worktree`），走失败重派，error 含违规明细与修正处方

#### Scenario: worktree 内 tasks.md 正常或不存在

- **WHEN** worktree 内 tasks.md 可解析、或 worktree 内无 tasks.md 路径
- **THEN** 复检放行，流程继续既有硬校验与 merge

### Requirement: 复检 fail-open 语义

复检执行路径上的任何异常（lint 函数抛错、读取失败）MUST NOT 阻断成功收口——记 WARNING 后放行。

#### Scenario: lint 函数内部异常

- **WHEN** 复检调用链内任何代码抛出异常
- **THEN** 捕获后记 WARNING（含 spec 名与异常摘要），流程继续 merge 与推进
