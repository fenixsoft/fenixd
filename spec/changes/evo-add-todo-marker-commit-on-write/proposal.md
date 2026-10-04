## 背景

自进化分析轮收尾时，框架代码 core/evolution.py:859 write_todo_marker() 把「自进化：…」裁决标记行写入消费项目主树的 .fenix/todo.md（该文件在项目 .gitignore 中显式例外、随仓库入库）。该写入路径及全部上游调用（ingest_item 四分支、accept/reject/delete、maintenance_runs 编排层）均无 git 提交动作，tracked 文件的未提交改动滞留主树；滞留盘点宽限（30 分钟）一到即升级 major 级 maintree_stray_wip_stale 告警并消耗一次 admin 车道 run 代提交。

实证：2026-10-04 potplayer-base 实例，10 条标记 03:31:02 写入（evolution run evo-1791052252 落地），03:31:51 被盘点看到（first_seen），04:01:54 告警（745a626f0884），admin-potplayer-base-1791057771 代提交 d8c60d9——input 77005 tokens、约 4 分钟，纯处置开销。

spec/knowledge/adr/ADR-060-framework-artifact-commit-points.md（accepted 2026-09-10）已确立「todo.md 类产物写入点即时 commit + push」原则；core/self_review.py:1974 _commit_todo（每日自省条目入库）是该原则的既有合规实现。缺口仅在自进化标记回写路径。

## 目标

- write_todo_marker 对 tracked 的 .fenix/todo.md 写入后就地完成 git add + commit（push 跟随 _commit_todo 既有形态），使滞留盘点不再看到该指纹、major 告警与 admin 代提交归零。
- 同一分析轮的多条目写入合并为单次提交，避免提交风暴。

## 非目标

- 不改 todo.md 的内容格式，不动 core/self_review.py 的既有提交路径。
- clear_todo 截断、knowledge_backfill.append_todo_line 等其他无提交写路径不在本 SPEC 范围（可另行评估立项）。
- 不改滞留盘点（maintree_stray_wip）的阈值与豁免逻辑。