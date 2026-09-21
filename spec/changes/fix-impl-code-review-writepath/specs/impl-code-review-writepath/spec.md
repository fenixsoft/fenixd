## ADDED Requirements

### Requirement: 收尾审查报告路径锚定 worktree

实现车道（implementer / fast-track）的收尾代码审查段 MUST 明确告知实现者：
`code-review.json` 的落盘路径是**当前工作目录（worktree）内的相对路径**
`.fenix/verify-progress/<spec>/code-review.json`，MUST NOT 用主树绝对路径写该文件。

#### Scenario: 提示词强调 worktree 相对路径

- **WHEN** `verify.impl_code_review` 为 `true`，构建 implementer 提示词
- **THEN** 收尾审查段 MUST 出现「相对当前工作目录（worktree）」的表述，且 MUST
  出现禁止用主树绝对路径写该文件的表述

#### Scenario: 开关关闭时零注入

- **WHEN** `verify.impl_code_review` 为 `false`
- **THEN** 提示词 MUST NOT 包含收尾审查段，且 MUST 与未引入本 change 时逐字节一致

### Requirement: 工作目录契约显式区分两台树

`agents/implementer.md` 与 `agents/fast-track.md` 的「工作目录（worktree 隔离，强制）」
段 MUST 把「验证进度目录」表述为**当前工作目录（worktree）内的**
`.fenix/verify-progress/`，并 MUST 显式提示「不是主树的同名目录」。

#### Scenario: 契约文本消歧

- **WHEN** 读取 `agents/implementer.md` 或 `agents/fast-track.md` 的工作目录段
- **THEN** MUST 出现「worktree 内」限定，且 MUST NOT 出现未限定的「验证进度目录
  `.fenix/verify-progress/`（框架已显式授权）」裸表述

## MODIFIED Requirements

### Requirement: run 级目录注入

`_run_claude` 向 agent 子进程注入 `--add-dir` 时，MUST 只授予该车道真实需要的目录。
主树 `<project_root>/.fenix/verify-progress` 的注入 MUST 按 `agent_type` 判定：
对**没有**主树 verify-progress 落点的车道（`implementer` / `repair` / `spec-review`）
MUST NOT 注入该目录。

#### Scenario: implementer 不再获得主树 verify-progress 授权

- **WHEN** 以 `agent_type="implementer"` 调用 `_run_claude`
- **THEN** 命令行 MUST NOT 包含 `--add-dir <project_root>/.fenix/verify-progress`，
  且 MUST 仍包含 `--add-dir <worktree>`

#### Scenario: verifier / planner 保留主树 verify-progress 授权

- **WHEN** 以 `agent_type` ∈ {`verifier`, `planner-plan`, `planner-judge`, `fast-track`}
  调用 `_run_claude`
- **THEN** 命令行 MUST 包含 `--add-dir <project_root>/.fenix/verify-progress`

#### Scenario: 未知/缺省 agent_type 保持既有注入

- **WHEN** `agent_type` 为 `None` 或未在车道清单中（maintenance / admin / dashboard 会话等）
- **THEN** 命令行 MUST 仍包含 `--add-dir <project_root>/.fenix/verify-progress`（零行为变化）
