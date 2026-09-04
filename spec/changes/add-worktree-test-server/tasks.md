# Tasks: add-worktree-test-server

实现依据（实施 agent 必读）：
- 能力定义 `specs/worktree-test-server/spec.md`；设计决策 design.md D1-D4
- 派发与 worktree 生命周期：`.fenix/core/agent_runner.py`（派发参数、run 终态处理）、`.fenix/core/worktree_manager.py`（worktree 创建/清理）
- 事故链路参考：2026-08-29 v2-overview-page merge-back 熔断（主仓树被 implementer 污染）

## 1. 代理服务脚本

- [x] 1.1 `tests/v2/dev-server.mjs`：Node http 代理——静态根目录取 worktree 的 `core/dashboard/static/`（argv/env 传入），`/api/*` 与 SSE 反代至 `http://127.0.0.1:8787`，流式响应禁缓冲透传；监听端口取 argv
- [x] 1.2 `tests/v2/playwright.config.js`：baseURL 改为 `process.env.V2_BASE_URL || 'http://127.0.0.1:8787'`

## 2. 框架生命周期接入

- [x] 2.1 派发前：agent_runner/worktree_manager 在 worktree 创建后启动 dev-server（端口按 D3 分配，冲突重试），将 `V2_BASE_URL` 注入 agent 运行环境；启动失败重试耗尽则 run 失败并告警
- [x] 2.2 回收：run 终态（成功/失败/异常/被杀）后终止服务进程；daemon 启动时清扫遗留 dev-server（按命令行标记识别）

## 3. 单元测试

- [x] 3.1 代理行为：静态命中 worktree 副本（改 worktree 文件立即可测）；API 反代返回与主服务一致；SSE 流分块透传不缓冲
- [x] 3.2 生命周期：run 被杀后服务进程回收；端口冲突时重试分配；config 的 env 覆盖与缺省回退

## 4. 验证与打包

- [x] 4.1 运行 `python3 -m pytest .fenix/tests/ -v` 确认无回归
- [x] 4.2 执行 `bash scripts/package.sh` 生成最新扩展包

## 验证修复（第 1 轮失败）

- [ ] 阅读 `spec/changes/add-worktree-test-server/verification-report.md`，定位「真实产品 Bug」并修复
- [ ] 修复后重跑验证确认通过
