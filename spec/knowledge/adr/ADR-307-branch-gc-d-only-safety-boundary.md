# ADR-307：分支 GC 删除只允许 -d 语义，宁漏勿误零备份

date: 2026-10-31
status: accepted

## Context

fenix 每轮实现/验证以时间戳新建分支，而 merge-back 销毁序列在保留场景刻意跳过删分支（分支承载首轮已提交成果），分支 ref 只增不减——2026-10-27 主仓库已累积 2157 条 `fenix/*` 分支，其中 2041 条已并入 main。对已合并分支做自动回收面对同一风险：扫描与删除之间分支状态可能被并发改变（新 worktree checkout、rebase 脱离基线、legacy 续做认领），删除动作一旦误删未合并内容即不可逆。同期人工清理对 116 条未合并分支采用「备份 ref（refs/fenix-branch-archive/）后删除」的手术式处置，但该口径不可自动化泛化：备份只是把 ref 膨胀换名字重演，绕过 git 合并判定则把安全性押在人工甄别上。

## Decision

已合并分支 GC 的删除动作只允许 `git branch -d`（git 拒绝未合并分支的删除语义），MUST NOT 使用 `-D`；不引入备份 ref 机制；全部判定守卫取「宁漏勿误」方向——spec 名解析失败、活跃状态不可判、legacy 登记在场、worktree 占用等任何不确定情形一律跳过不删。由此自动化路径的最坏结果是漏删（下轮重扫），不存在丢内容路径。GC 挂既有 worktree 陈旧清扫（daemon 启动触发）不新增调度面；活跃豁免复用 `_branch_protected_by_state` 单一来源并以 STATE.md 显式活跃状态集补齐其未覆盖状态。后续任何触碰分支 ref 生命周期的自动化（新回收通道、扩扫描前缀、改判定条件）同受此约束；需要 `-D` 语义或备份 ref 的处置只限人工执行，自动化扩权须显式 supersede 本 ADR。

## Consequences

- 已合并分支删除零内容损失（提交仍从基线可达、可按 sha 重建），代价是未合并存量分支永不自动收敛，须人工甄别处置。
- 宽限期（默认 7 天）成为 deliverables D1 读侧兜底（`git show <branch>:tasks.md`）与验证 diff 参照的承诺窗口，窗口内分支保证在场。
- 活跃豁免的 STATE 显式状态集为静态清单：STATE.md 新增活跃状态时必须同步枚举，否则该状态 spec 的已合并分支可能在合并超宽限期后被误收（`_branch_protected_by_state` 单一来源部分自动跟随）。
- 收敛速度绑定 daemon 重启节奏：长驻运行期间新增的已合并分支延迟到下次启动回收，属接受代价。
