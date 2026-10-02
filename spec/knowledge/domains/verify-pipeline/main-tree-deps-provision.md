# 主树依赖供给
<!-- knowledge: capability=main-tree-deps-provision rev=1 sources=spec/archive/2026-09-18-add-main-tree-deps-provision -->

主树路径执行契约 prepare 前的依赖预检与预装：被管项目主树只被 merge-back 写入、无人手工安装依赖，node_modules 缺失时自动补齐，消除 `tsc: not found` 类环境阻塞。

## 现行规则

- 预检与预装：验证链路与 merge 后重建在主树执行契约 prepare 前，对 prepare 步骤涉及的子目录集合（各步骤 `cwd`，缺省 `.`）执行依赖预检——目录含 `package.json` 且缺 `node_modules` 时按 deps_mode 解析结果预装依赖。
- 主树自装一律走 prefer-offline 安装：`npm ci --prefer-offline --no-audit --no-fund`，失败回退 `npm install --prefer-offline --no-audit --no-fund`。
- 幂等零开销：`node_modules` 已存在时不运行任何安装命令直接 prepare；目录无 `package.json` 时跳过预装、不报错。
- 预装失败不短路：记 WARNING 日志后继续执行 prepare；prepare 因缺依赖失败时走既有「prepare 失败＝验证环境错误」门禁链路，不新增第二套失败通道。
- 留痕：预装动作与结果记日志（目标目录 + 结果；成功 INFO、失败 WARNING 含 stderr 尾部），供 admin 从日志定位。
- 三处主树裸跑点全部接入：纯 cli 场景集的主树 prepare、`verify.static_scope=main`（默认）且场景集含 web/api 场景的主树 prepare、merge-back 后 `_run_dist_build` 主树 dist 重建前的 prepare——覆盖面不留缺口。
- worktree 路径行为不变：serving worktree / 实现 worktree 沿用既有 `provision_worktree_node_modules`（hardlink 源=主树语义）。

## 溯源

- 2026-09-18 add-main-tree-deps-provision（spec/archive/2026-09-18-add-main-tree-deps-provision） — 新增主树 prepare 前依赖预检与预装，覆盖三处主树裸跑点（此前依赖供给只覆盖 worktree 路径，主树路径零供给、首次验证必踩 exit 127 环境阻塞）
