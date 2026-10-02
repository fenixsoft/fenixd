<!-- knowledge: capability=deliverable-declaration-resolution rev=2 sources=spec/archive/2026-09-23-add-declaration-relocation-protocol,spec/archive/2026-09-26-fix-relocation-writeback-layer -->

# 交付物声明统一解析契约

生效声明的单一权威解析入口：分层读取、来源标注、可信基线快照——所有声明消费方共享同一读取基准，写回层据此判定落点。

## 现行规则

- 单一权威源：系统提供唯一入口解析「某 SPEC 在当下适用的交付物声明集合」，全部消费方（收工守卫、晋升 lint、预分类、裁决、提示词组装、fast-track 快照、重定位）经该入口读取，不得由各消费点自行拼接 `project_root/spec/changes/<spec>/` 路径直读主树。解析入口接收 spec 名与可选分支/worktree 上下文，返回与既有 `extract_declared` 同构的结果（`deliverables`/`references` 两组，保序去重）。
- 分层解析优先序：分支/worktree 版本优先（实现期真实在测的那份），在分支/worktree 不可用或不含声明段时回退主树版本。读取分支版本以只读方式（`git show <branch>:spec/changes/<spec>/tasks.md` 或 worktree 内文件读），不写主树。回退 fail-safe：分支读取失败（非零退出、超时、路径不存在）或解析异常 → 回退主树；两处均不可用 → 返回空结果（等价「无声明段」，守卫跳过），并审计留痕说明回退去向。
- 写回层来源标注：解析结果附带 `source`（`worktree`/`branch`/`main`）与 `spec_dir`，供消费方判定「修正写入落点是否与读取基准同源」。`spec_dir` 用于读取与写入两个方向语义一致：作写入落点时必须是实际命中层——worktree 命中为 worktree 内 spec 目录；主树命中为主树 spec 目录（此时守卫读取基准即主树，就地写入同源，允许且不得禁止）；`source == "branch"` 时 `spec_dir` 为 `None`（无落盘位置），消费方不得回落主树 `spec/changes/<spec>/` 作为修正写入落点，须改走打回/凭据通道（见 `relocation-writeback-layer`）。判据不得把 `main` 与 `branch` 同等归为「一律不可写」——`main` 来源的就地写入是同源写入，禁止它会误伤既有可用路径。
- 可信基线快照：实现 run 派发时，将**派发时刻主树**的声明集合快照持久化到实现 Agent 不可触及的位置（`.fenix/verify-progress/<spec>/declaration-baseline.json`），记录声明条目（path + kind）、快照时刻、触发 run id。快照不在 worktree 内、不经实现 Agent 路径写入——它是声明收缩防护（见 `implementer-deliverable-gate`）的独立参照系，读取方为守卫/裁决流水线。快照写入失败不阻塞派发（WARNING 留痕），该轮收缩防护降级为「无基线可用」保守策略。
- 解析成本：纯文件/对象库读取（worktree 文件读或 `git show`/`git cat-file`），不触发 LLM 调用、测试执行或网络请求。

## 溯源

- 2026-09-23 2026-09-23-add-declaration-relocation-protocol（spec/archive/2026-09-23-add-declaration-relocation-protocol） — 建立统一解析入口、分支优先分层回退、派发时可信基线快照与零成本契约
- 2026-09-26 2026-09-26-fix-relocation-writeback-layer（spec/archive/2026-09-26-fix-relocation-writeback-layer） — 解析结果增加 `source`/`spec_dir` 写回层标注：写入落点须为命中层，`branch` 来源不可就地写入、`main` 来源同源允许
