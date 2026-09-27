# ADR-060：框架产物入库时机——归档残留挂 push 尾部收口，即时消费产物写入点即提交

date: 2026-09-10
status: accepted

## Context

spec 归档一天可发生多次，归档产生的目录移动需要入库才对后续 agent 可见；提交若发生在归档动作点上，会逐次打断 push 语义并与 spec_done 的 push 相互竞争。另有一类产物（如 todo.md 条目）恰恰要求后续从 main 分出的 worktree agent 立即可见——未提交文件对它们不存在。两类产物的入库时机需要分别钉死。

## Decision

- 归档残留提交统一挂在 **push 流程尾部**批量收口：一次提交收掉当天全部残留，不逐归档动作提交；`git add` 限定 spec/changes 路径（禁 `add -A`），避免卷入主树无关改动。
- 批量收口失败（冲突等）降级 WARNING 留待下次 push 重试，**不阻塞 spec 终态**。
- 必须立即被后续 worktree agent 看见的产物（如 todo.md）在**写入点即时 commit + push**，提交仅含该文件；push 失败降级 WARNING 不重试风暴。
- 两类提交机制独立，不叠加、不互相等待。

## Consequences

- 归档与 push 的时序耦合消失，主树不留长期归档残留。
- 写入点提交带来每日小 diff 的 commit 噪音——保证「新 agent 据此提出 spec」的可见性，代价可接受。
