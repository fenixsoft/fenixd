# Tasks: 修复 improve-run-lifecycle-governance 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/improve-run-lifecycle-governance/verification-report.md`，定位「真实产品 Bug」的根因并修复
  - 结论：17 场景中 2 通过 / 15 失败。15 例失败**全部为验证脚手架 mock 层未注入场景专用治理固件所致（伪失败），非 fenixd 产品缺陷**。
    - 根因证据：`empty-state` 场景 `/api/specs?project=fenixd` 实际返回 fenixd 真实 56 个 SPEC（项目 `openspec/changes/` 下真实存在 59 个），证明后端过滤正确、mock 回落为真实数据。
    - dashboard 渲染层健康：`.spec-info-row` 仅当 `error` 非空才渲染、`.alert-item` 无 CSS 隐藏缺陷；全部 17 场景 `no_console_error` 均通过；两处正向断言（概览标题/卡片网格、活跃 Agent 运行统计块、alert-banner/alert-item、activity-card）均通过。
    - 治理数据（`governance-*` 行与 `recovery deferred`/`backoff until`/`dispatch_stalled`/`liveness judge unavailable` 文本）缺失，需由验证 `mock_api` 按场景注入固件——属验证基础设施缺陷，依 proposal.md 界定不在本 fix SPEC 范围。
  - 范围内**无真实产品 Bug 可修复**。详见本目录 `verification-report.md`。

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过
  - 不适用：本仓库无 `package.json`/`tsconfig.json`/`vite`，dashboard 为纯静态资源由 `package.sh` 直接拷贝，无编译步骤。无 TS/前端代码需构建。
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归
  - 全量运行 **659 passed**。3 例 pre-existing failure（`tests/test_core.py::TestRouteTableGuard`/`TestEngineRouteCrossCheck`，路由表提取 + 测试 mock 的 await 用法）与 run-lifecycle 治理无关，非本 SPEC 引入，不在范围。
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
  - 成功生成 `dist/fenixd-20260828.tar.gz`（332K）。
