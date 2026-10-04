# ADR-232：蒸馏 run 主树直跑，格式对账与 git 提交不进 agent

date: 2026-10-05
status: accepted

## Context

归档蒸馏是 LLM 任务（散文重写无可替代），但 git 操作与格式对账若也交给 agent，会引入 merge-back 复杂度与假成功风险。真相源是 spec 元数据层而非产品代码，且主树常态堆有用户未提交改动，worktree 隔离并非天然必要。

## Decision

蒸馏 run 由 daemon spawn `claude -p` 后台任务、cwd 主树直跑（不经 worktree、无 merge-back），写路径限定 `spec/knowledge/` 一个目录；与 fast-track 的 worktree-implementer 模式 deliberately 不同。格式对账与 git 提交不进 agent：run 结束后由 daemon 侧确定性校验脚本 `validate_knowledge` 对账（marker/sources/行数/链接/ADR 不可变），违规回反馈给 run 修正（≤2 轮），通过后由 daemon pathspec 限定提交；放弃产出时由 daemon 侧 restore 并清理未跟踪新增，不留半成品。

## Consequences

省掉 merge-back 与 worktree 生命周期成本，爆炸半径收敛在单目录。代价：蒸馏 run 与用户工作区共用主树，越界写面只能 git status 对账告警、不能自动回滚（避免吞掉用户未提交改动）；散文语义质量无法机械校验（校验拦格式不拦「写得烂」），靠提示词风格约束与 audit 车道持续返工。
