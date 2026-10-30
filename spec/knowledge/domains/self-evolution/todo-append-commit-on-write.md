# todo.md 追加写后就地提交

<!-- knowledge: capability=todo-append-commit-on-write rev=1
     sources=spec/archive/2026-10-30-evo-add-todo-append-commit-on-write -->

todo.md 追加/改写写路径的即时入库：无提交写路径写入 todo.md 会与分支改动路径重叠、被 merge-back WIP 重叠闸门连拍拦截、最终烧 admin run 代提交——本能力把 ADR-060 的「写入点即时 commit+push、提交仅含该文件」原则覆盖到全部追加调用方。

## 规则

- **追加写路径写后即时入库**：`append_todo_line`（core/knowledge_backfill.py，todo.md 追加行的唯一共享写函数，22 个调用方：蒸馏重试登记、蒸馏/回填各类登记、audit 转写失败登记等）发生实际追加后，在该写路径内完成一次路径限定的就地 git 提交（`git add` 与 `git commit` 均以 `.fenix/todo.md` 为 pathspec）并尝试 push——提交仅含该文件（不卷入索引中并发暂存的其他内容），提交后该文件无未提交改动。
- **改写写路径同款收口**：同文件的 `upsert_todo_line`（audit 升级聚合行等场景）发生实际写盘（新增/整行替换/清理）后经同一提交助手完成同款提交；零写盘（幂等命中、纯清理无残留）不产生提交。
- **仅实际写入才提交**：幂等去重命中（待追加行已存在、本次调用未发生实际写入）零 git 提交。
- **降级不阻断**：todo.md 未被 git 跟踪（含所在目录非 git 仓库）时写入行为与无提交时一致、不报错；提交失败（如 index.lock 竞争）或 push 失败时写入不回滚、不向调用方抛错，经日志留痕（push 失败降级不重试，本地提交不受影响）——最坏情形回到「merge-back 闸门保守拦截 + admin 代提交」现状，不劣于无此能力。
- **git 在文件锁外执行**：就地提交的 git 子命令在 todo.md 的 flock 释放后执行，MUST NOT 拉长持锁窗口阻塞 code_fix、self_review 等并发追加方。
- **分支语义**：分支 worktree 内调用时提交落在该 worktree 分支上、随合并带回；高频登记日会产生多个小提交，为 ADR-060 明确接受的形态。

## 关键行为

提交动作收口在共享写函数内而非逐调用方改造——单点最不漏，且幂等去重天然保证只在真实追加时提交。主题行固定形态（`[fenix] todo: <来源摘要>` 族），git log 可对账。

## 溯源

- 2026-10-30 evo-add-todo-append-commit-on-write（spec/archive/2026-10-30-evo-add-todo-append-commit-on-write） — 新增本能力：append_todo_line 与 upsert_todo_line 写后就地提交（pathspec 限定、幂等零提交、untracked/git 失败降级不阻断、git 在 flock 外）（动因实测：两起同链条事故——未提交 todo 行与分支改动重叠被 WIP 闸门连拍 5 次、烧 1 次 admin run 代提交解除）
