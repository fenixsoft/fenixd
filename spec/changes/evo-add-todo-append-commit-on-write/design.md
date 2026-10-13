# Design: add-todo-append-commit-on-write

## Context

- append_todo_line 是 todo.md 追加写的唯一共享口：_todo_write_lock（flock）→ 读改写 → atomic_write_text 原子回写 → 整行幂等去重；22 个调用方分布于 core/knowledge.py:627、core/knowledge_backfill.py（20 处）、core/knowledge_audit.py:1533。
- 同文件的 ``upsert_todo_line``（audit 升级聚合行，唯一调用方 core/knowledge_audit.py:1604）是第二条无提交 todo.md 写路径：实际写盘（新增/整行替换/清理）同样滞留主树，其邻近的 disputed 注记提交 pathspec 为 spec/knowledge、不覆盖 todo.md，本 SPEC 一并收口。
- 可复用形态两处先例：core/self_review.py:2276 _commit_todo 与 core/evolution.py 的 _commit_todo_marker（前身 SPEC 2026-10-12-evo-add-todo-marker-commit-on-write 落地）——均为 git add -- .fenix/todo.md + 带 pathspec 的 git commit -- .fenix/todo.md + push（失败降级 WARNING），LC_ALL=C 环境防本地化文案误报，git 子命令 30s 超时，且明确要求 git 不进 flock 临界区。

## Goals / Non-Goals

- Goals：单点收口全部追加调用方；仅实际写入才提交；git 异常不阻断写路径、不向调用方抛错。
- Non-Goals：不改闸门语义（evo-merge-back-wip-overlap-gate 在途）；不动 write_todo_marker 与 clear_todo；不引入后台批量提交器。

## Decisions

1. **提交放在共享函数内而非逐调用方**：22 个调用方逐个加提交必然漏改（todo 条目给出的调用方清单就漏了 knowledge_audit.py:1533 且文件名有误）；共享口单点最不漏，且幂等去重天然保证只在真实追加时提交，无空提交噪音；upsert_todo_line 同理在函数内单点收口，其返回值即「是否实际写盘」，天然充当提交开关。
2. **复用既有提交助手而非新写第三份**：优先经函数内延迟导入复用 core/evolution.py 的提交助手（commit_todo_marker/_commit_todo_marker，已带 LC_ALL=C、30s 超时与降级语义）。助手主题行现硬编码为「[fenix] evolution: 自进化标记回写」（core/evolution.py:1003），现样复用与决策 5 的主题行形态互斥，须向后兼容地给助手加可选主题行参数（缺省维持现行为），故 core/evolution.py 在交付面内。经查 evolution 顶层仅导入 core.fs_utils/core.timelib（无 knowledge_backfill/knowledge 顶层依赖），函数内延迟导入无循环依赖，主分支可行；若实测有变，则把助手下沉至共享底层模块后两侧引用（交付面相应调整为新建共享模块 + evolution.py 引用）。
3. **git 在锁外执行**：与 write_todo_marker 同款约束——锁内完成写入与去重判定，释放 flock 后再 add/commit/push，避免拉长持锁窗口阻塞 code_fix、self_review 的并发追加。
4. **失败降级不抛错**：untracked（含非 git 仓库）跳过提交；commit 失败经日志留痕、待下次写入再试；push 失败降级不重试——最坏情形回到现状（闸门保守拦截 + admin 代提交），不劣于今天。
5. **提交信息形态**：固定主题行（如 [fenix] todo: <来源摘要>），与 _commit_todo 的 [fenix] daily self-review 及 write_todo_marker 先例同族，git log 可对账。

## Risks / Trade-offs

- 高频登记日会产生多个小提交：实测蒸馏登记两周 8 次，量级可接受，ADR-060 明确接受该形态。
- pathspec 提交会带走同刻其他来源写入 todo.md 的未提交行：这正是期望行为（todo.md 的全部未提交内容都是可合回产物），write_todo_marker 先例同此。
- 分支 worktree 内调用时提交落在该 worktree 分支上：与现状「分支尾部追加 todo.md 节随合并带回」一致，不产生新行为。