# 提案：测试目录忽略规则收敛与回归面恢复（test-infra-gitignore-convergence）

## 背景与问题

框架草稿清理器 stash_guard 的 `_purge_ignored_brought_in`（fenixd core/worktree_manager/stash_guard.py:1653）在 merge-back 时把「本次合回新增（--diff-filter=A）且被 gitignore 命中」的 tracked 文件一律 git rm --cached 剥出索引，设计假设为「tracked 且被忽略 = 误提交的运行时草稿」（check-ignore --no-index 批量判定，源码注释 :1743-1748 明言依赖 --no-index 让 tracked 路径也判忽略），无任何内容性质豁免。

本项目存在与之长期冲突的规约组合：

1. CLAUDE.md:32 明文要求所有 test-* 测试文件放 .test/；
2. .gitignore 第 11、40 行双重声明忽略 .test/ 整目录；
3. gitignore(5) 官方语义：父目录被排除时子文件不可用 ! 反包含。

后果：2026-09-07 至 11-25 同指纹自动剥离 5 次，对象全部是 SPEC 验收 commissioned 的合法测试基建（11 个文件约 3300 行），「剥真草稿」对照组 0 次：

- 922ce3d（09-07）：multi-user-sync / notes-standalone-sync / notes-sync-integration 单测（748 行）；
- 52060a2（09-09）：test-panel-input-autofocus.html 测试页（382 行）；
- 1245250（09-17）：quick-links 单测 / adapter / e2e（834 行）；
- e6457e5（09-18）：stock sync 单测 / adapter / e2e（870 行）；
- a2e655f（11-25）：.test/helpers.ts（带入索引 36 秒后被剥）。

代价：显性——11-25 剥离令 code-review-fix 批次A fresh worktree 回归 esbuild 打包失败，追加定向修复 run code-fix-1795628319（1.3737 美元 / 248.6 秒 / 26 轮）；隐性——11 个测试文件退出版本控制（仅存主树 untracked 副本），fresh worktree 回归面自 9 月起静默塌缩（磁盘 21 个 .test.ts 仅 4 个 tracked，.fenix/verify.yaml regression 按磁盘 glob 收集、缺席即静默跳过），至少 3 份在途 SPEC 被迫写入绕行条款（quick-links-standalone-sync/design.md:159、tasks.md:76/83/95；stock-account-finance-sync/tasks.md:27）。

## 目标

1. .gitignore 对 .test/ 的处理从「整目录忽略」收敛为「只忽略运行时产物与一次性调试脚本」，使测试基建可合法 tracked，从源头解除「规约要求 tracked × gitignore 判忽略 × 清理器必剥离」三方冲突。
2. 恢复测试基建版本控制：9 月 4 次剥离的 10 个文件（7 个回归脚本 + 1 个测试页 + 2 个 e2e 脚本）重新入库；磁盘其余 never-tracked 回归脚本逐个判定入库或入留档区，遏制回归面静默塌缩。
3. 收敛后 .test/ 下不留成片未表态散件（主树 stray-WIP 清扫面不扩大）。

## 方向

采用 .gitignore 收敛而非 stash_guard 加豁免：5 次复发全部集中于本项目规约矛盾，框架侧豁免（扩展名白名单）会为单个项目错配波及所有项目，且「剥离前核查引用」形态在框架层不可行（框架无法知道引用关系）；收敛同时解除在途 SPEC 交付物守卫「gitignore 拒 new / worktree 缺件打回 reference」双难；stash_guard 对真运行时产物（verify-shots 截图等）的剥离是设计预期，保持不动。

范围外（显式排除）：.fenix/ 下 8 个 tracked-但被忽略 的框架基建文件（同类冲突另议）；fenixd 侧 stash_guard.py 改动；在途 SPEC 已写入的绕行条款不回改（避免与在飞车道互踩）。