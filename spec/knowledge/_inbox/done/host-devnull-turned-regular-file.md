# 宿主 /dev/null 被写成普通文件 → git 配置隔离全灭、测试大面积假失败

## 背景

code-fix 车道回归重试轮排查 44 例失败：git init 报
`fatal: bad config line 1 in file /dev/null`（exit 128）、另有大量
Timeout(>10s) 与「非 git 仓库，跳过归档提交」形态。失败面与当批代码改动
零交集，逐层对照实验后定位为宿主 /dev/null 设备损坏，非代码回归。

## 结论（当前事实）

- 宿主 /dev/null 可能被静默替换为**普通文件**（实测 102 字节，内容为 zsh
  初始化报错文本 `zsh:unalias:1: no such hash table element: unsetenv`）；
  一旦变普通文件，所有 `2>/dev/null` 类写入都会覆盖它，损坏自我延续。
- 判别法：`stat -c %F /dev/null` 输出非 `character special file` 即坏。
- 修复：`rm -f /dev/null && mknod /dev/null c 1 3 && chmod 666 /dev/null`。
  恢复设备后普通重定向写入只被丢弃、不再改变文件类型，稳态健康。
- 症状指纹：`GIT_CONFIG_GLOBAL=/dev/null`（测试隔离 git 配置的常见手法，
  tests/ 下 test_knowledge*.py、test_spec_archive.py、
  test_move_distill_trigger_to_push.py 等多文件在用）在 git ≥2.54 下读坏
  设备即 fatal exit 128；下游呈现 git init 失败、「非 git 仓库」warning、
  distill 子进程 Timeout 三种失败形态，与代码改动零交集时优先查宿主。
- 归 daemon-runtime 域「宿主环境已知脆弱面登记」。

## 证据

- 损坏态：`stat -c '%F %s mtime=%y' /dev/null` →
  `regular file 102 mtime=2026-11-13 01:04:32 +0800`；
  `head -c 200 /dev/null` 内容即上述 zsh 报错两行。
- 对照实验：`GIT_CONFIG_GLOBAL=/dev/null git init -q /tmp/pg` 复现 exit 128
  （GLOBAL/SYSTEM 单独或联合、`-C` 与路径参数各形态均挂；SYSTEM 单设亦挂）。
- 重建设备后，上轮回归失败的 8 个测试文件全量重跑 236 例全绿（含原失败 44 例）。
