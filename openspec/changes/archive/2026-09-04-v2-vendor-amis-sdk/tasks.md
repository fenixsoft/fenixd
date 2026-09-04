# Tasks: v2-vendor-amis-sdk

实现依据(实施 agent 必读):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md 的「Task 1」节(含精确命令)
- 设计 docs/superpowers/specs/2026-08-29-amis-dashboard-v2-design.md §2

## 1. Vendor SDK

- [x] 1.1 创建 `/tmp/amis-pkg` 与 `core/dashboard/static/v2/`;若 `/tmp/amis-6.13.0.tgz` 不存在先 `cd /tmp && npm pack amis@6.13.0`;tarball 提取 5 个文件并拷贝到 static/v2/(命令见计划 Task 1 Step 1)
- [x] 1.2 验证文件完整:5 个文件存在,sdk.js 为 MB 级合法 JS(计划 Task 1 Step 2)

## 2. 服务可达验证

- [x] 2.1 确认 dashboard 服务运行中(python3 bin/fenix_dashboard.py --serve 或已在 tmux 运行),curl 验证 `/v2/sdk.js` 返回 200、`/` 仍为老版
