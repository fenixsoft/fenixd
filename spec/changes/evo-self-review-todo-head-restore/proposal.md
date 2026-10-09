# Proposal：self-review-todo-head-restore

## 背景

自省台账 .fenix/todo.md 曾被整文件清空（2026-10-09 15:54 本地，操作者未核实），而 daemon 全部回写路径对「工作树空但 HEAD 有内容」无任何防护：core/self_review.py:2069-2089 _append_todo._do 读到空文件后直接追加落盘。该风险已于 2026-10-10 兑现——当日自省把新节追加在被清空文件上并提交 3c6eb90，402 行历史（8 个日期节）从工作树与 HEAD 双重缺席，仅存于历史提交 0a17382。另 core/dashboard/routes/settings_routes.py 的 POST /api/todo 端点整文件覆写 todo.md、不持锁、成功零日志，是未留痕写者中风险最高的一处。fs_utils 的 flock 与原子写只防并发截断，不防内容丢失。

## 目标

1. 回写前自愈：daemon 写 todo.md 前发现工作树为空/缺失而 HEAD 版非空时，从 HEAD 读回基线再落写，并 WARNING 留痕。
2. 豁免通道：提供配置开关（缺省开启恢复），有意清空台账时可关闭，避免恢复逻辑与人工意图打架。
3. 收敛未留痕写者：dashboard 覆写端点持同一把锁并留痕，消除「静默覆写无从追责」的盲区。

## 非目标

- 不翻转 read_todo 缺省（全局行为与成本变更，另有 evo-add-self-review-todo-fallback-honesty 在位，属独立变更）。
- 不改 fs_utils 模块契约（其注释约定只依赖 stdlib，git 助手放 self_review 侧）。
- 不做历史台账的一次性数据修复（0a17382 为底并入 10-10 节的重提交属运维操作，由人工执行）。

## 方案概要

self_review.py 新增共用助手 _load_existing_with_head_rescue（git show HEAD:.fenix/todo.md 读回，subprocess 与 _commit_todo 同口径、30 秒超时，失败静默回退现状），_append_todo/_skip_review/_remove_resolved 三处接入；config.py 的 get_self_review_config 增加 todo_head_restore 开关（缺省 true）；settings_routes.py 的 _write_project_doc 对 todo.md 持 with_file_lock 并加成功 INFO/覆空 WARNING 留痕。