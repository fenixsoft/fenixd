# 自进化标记写后即时入库
<!-- knowledge: capability=todo-marker-commit-on-write rev=1
     sources=spec/archive/2026-10-12-evo-add-todo-marker-commit-on-write -->

自进化裁决标记写入项目主树 .fenix/todo.md 的写路径内就地完成该文件的 git 提交，tracked 文件不滞留未提交改动，主树滞留盘点不再看到该指纹，major 级 maintree_stray_wip_stale 告警与 admin 代提交不因此路径产生。

## 规则

- 写后即提交：标记写入 tracked 的 .fenix/todo.md 后，框架在写路径内完成该文件的 git add 与 commit，主树对该文件无未提交改动残留；push 跟随提交执行。
- tracked 判定：以 `git ls-files` 判定 todo.md 是否被 git 跟踪；未跟踪（含目录非 git 仓库）直接跳过提交，写入行为不变、不报错。
- 提交粒度：同轮同项目多条目合并为恰一个提交；一轮涉及多个项目时按项目各一次，不存在跨项目单提交。
- pathspec 限定：`git add -- .fenix/todo.md` 与 `git commit -- .fenix/todo.md` 均带 pathspec，提交仅含该文件——不带 pathspec 的 commit 会把索引中并发暂存的其他自动化产物（merge-back、交付物守卫等）卷进本提交并随 push 外泄。
- 批量与单点分治：批量落条目路径（ingest_item 内部调用）关闭提交开关，避免逐条提交风暴；由编排层在一轮 ingest 循环结束后对本轮涉及的项目集合按项目各触发一次合并提交。accept / reject / delete 三个单点写路径保持写后即提交。
- 锁外执行：提交动作在 todo.md 的 flock 释放后执行，git 子命令（各 30s 超时）不进锁内，不拉长持锁窗口阻塞 code_fix / self_review 的并发追加。
- 失败降级：commit 失败（含 index.lock 竞争）捕获后经既有日志通道留痕，不回滚写入、不向调用方抛错、不做自动重试（下一次写入自然再试）；push 失败降级 WARNING 不重试，本地提交不受影响。
- 提交信息形如 `[fenix] evolution: 自进化标记回写 <date>`，遵循仓库惯例。

## 溯源

- 2026-10-12 evo-add-todo-marker-commit-on-write（spec/archive/2026-10-12-evo-add-todo-marker-commit-on-write） — 新增标记写后即时入库全部规则（tracked 判定跳过、按项目合并单提交、pathspec 双限定、批量/单点分治、锁外提交、commit/push 失败降级）
