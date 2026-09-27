# ADR-023：实现车道 worktree 隔离——cwd 锚定、分支自包含、merge-back 回主树

date: 2026-09-02
status: accepted

## Context

worktree 隔离曾被两个缺口架空：agent 子进程继承 daemon 的主树 cwd，prompt 相对路径全部解析到主树，实现者编辑与提交直接落 main、worktree 恒 clean；SPEC 源文件未提交进 git，worktree 内不可见，agent 找不到 SPEC 后回落主树直接编辑，绕过隔离与审批门禁。读侧（结果文件、任务进度）若与写侧不同层，进度展示与结果读取全断。

## Decision

- 写读同层，cwd 锚定：agent 子进程 cwd = worktree 路径，相对路径解析、编辑、提交全部落在隔离区（--add-dir 仅为双保险）；实现结果与任务进度的读取一律 worktree 优先、主树兜底，读取位置与实际写入位置一致。
- 隔离分支自包含：派发前把 SPEC 目录播种进 worktree 并提交到隔离分支，agent 的全部工作（读 SPEC、标 tasks、写结果）随分支走，分支内容与推送内容一致。
- 实现成功后由框架在状态推进前把分支 `merge --no-ff` 回主树，verifier 验证的是合并后的主树；merge 前以 merge-base 祖先检查保证幂等；合并失败标 error 不推进状态，保留可重试态（worktree 重建重试）。
- merge-back 挂在 pm_engine 的状态推进边界，worktree_manager 只管 worktree 生命周期。

## Consequences

- 隔离真实生效：实现期主树保持干净，交付物与审计历史都在分支上；merge-back 成为实现链标准环节，其主树冲突面由 ADR-021 的自愈语义兜底。
- Administrator 处置不走此隔离（主树直写，见 ADR-012）；verifier 车道验证运行于合并后的主树，无独立 worktree 播种需求。
