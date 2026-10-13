# Proposal: add-todo-append-commit-on-write

## Why

2026-10-13 dsh-primary-acceptance-switch 合回时，主树工作区一行未提交的 knowledge-distill 重试待办（当日本地 14:11 由蒸馏失败登记写入）与分支的 todo.md 改动路径重叠，被 merge-back WIP 重叠闸门连拍 5 次拦截（2026-10-13T14:54:45Z→15:01:15Z，重试计至 4/6），最终消耗 1 次 admin 车道 run（admin-dsh-primary-acceptance-switch-1791903542）代提交 517c92e1 才解除，合并延迟约 8.5 分钟。同根因 2026-09-30 已发生一次（add-timelib-callsite-migration 合回被挡，admin 提交 f596c899 代提交解除）——两次同一链条：无提交写路径写入 todo.md → 与分支改动路径重叠 → 闸门阻塞 → 烧 admin run。

写路径源头是 core/knowledge_backfill.py:188 的 append_todo_line（todo.md 追加行的共享写函数：flock → 读改写 → atomic_write_text 原子回写 → 整行幂等去重），函数体全程无任何 git 提交，调用方共 22 处（core/knowledge.py:627 蒸馏重试登记、knowledge_backfill.py 内 20 处、core/knowledge_audit.py:1533 audit 语义项转写失败登记）。仅蒸馏失败登记约两周即触发 8 次（09-30×1、10-02×4、10-06×2、10-13×1），日间写入后若无提交收口即滞留主树，下一次触及 todo.md 的合回即复现。

ADR-060-framework-artifact-commit-points（accepted）已确立「todo.md 类产物在写入点即时 commit+push、提交仅含该文件」原则；直接前身 2026-10-12-evo-add-todo-marker-commit-on-write 只落地了 write_todo_marker 路径，其非目标段明确把 knowledge_backfill.append_todo_line 等写路径排除（「可另行评估立项」）。本 SPEC 即该预留的落地。

## What Changes

- 在 append_todo_line 共享写函数内部完成实际追加后，追加一次路径限定的就地提交（形态与 core/self_review.py _commit_todo、core/evolution.py commit_todo_marker 一致：git add -- .fenix/todo.md、带 pathspec 的 git commit、尝试 push），单点覆盖全部 22 个调用方，无需逐调用方改造。
- 同文件的 upsert_todo_line（audit 升级聚合行等场景的 todo.md 写路径）在实际写盘（新增/整行替换/清理）后走同一提交助手收口——它与 append_todo_line 同属「无提交写路径写入 todo.md → 闸门阻塞」事故链，且其调用点邻近的知识提交 pathspec 为 spec/knowledge、不覆盖 todo.md。
- 仅在实际写入（append 幂等去重未命中 / upsert 实际写盘）时提交；todo.md 未被 git 跟踪或 git 失败时降级 WARNING，不阻断写路径、不向调用方抛错。

## Scope

### In Scope

- core/knowledge_backfill.py append_todo_line 与 upsert_todo_line 的写后就地提交。
- tests/test_knowledge_backfill.py 覆盖：实际追加触发提交且提交仅含 todo.md、幂等去重不产生提交、untracked/无 git 降级不阻断。

### Out of Scope

- write_todo_marker 路径（前身 SPEC 已覆盖）与 clear_todo 截断路径（延续前身非目标口径，另行评估）。
- merge-back WIP 重叠闸门语义（在途 evo-merge-back-wip-overlap-gate，不动）。