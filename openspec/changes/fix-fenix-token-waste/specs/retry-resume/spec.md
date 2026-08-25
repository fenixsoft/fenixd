# retry-resume Spec

## ADDED Requirements

### Requirement: 失败重试续跑
Fenixd SHALL 在 implementer 失败重试时复用同一 worktree 与同一 claude session（`--resume`），从失败处续跑而非从头全量重跑。首次 attempt SHALL 创建新 worktree 并启动新 session；后续 attempt SHALL 在同一 worktree 内使用 `claude --resume <session_id>` 接续。若续跑不可行（如 session 已丢失），SHALL 回退为全新运行并记录 WARNING。

#### Scenario: 重试复用 worktree 与 session
- **WHEN** implementer attempt 1 失败
- **THEN** attempt 2 复用 attempt 1 的 worktree 目录，并以 --resume 接续原 session，而非新建 worktree

#### Scenario: 首次运行正常创建
- **WHEN** implementer 首次运行（无前置 attempt）
- **THEN** 创建新 worktree 并启动新 session

#### Scenario: session 丢失时回退全新运行
- **WHEN** 重试时原 session 已不可恢复（如超时清理）
- **THEN** Fenixd 记录 WARNING 并回退为全新 worktree + 新 session 运行

### Requirement: run_id 每次 attempt 独立
Fenixd SHALL 为同一 spec 的每次 attempt 生成独立 run_id（带 attempt 序号），产物文件与尝试一一对应。不同 attempt 的产物 SHALL 写入不同文件，不得混装在同一 jsonl 中。

#### Scenario: attempt 序号进入 run_id
- **WHEN** 某 spec 的 implementer 第 2 次 attempt 开始运行
- **THEN** 其 run_id 包含 attempt 序号（如 `impl-<spec>-<ts>-a2`），产物写入独立 jsonl
