# Tasks: 修复 fix-improve-run-lifecycle-governance 验证发现的缺陷

## 1. 复核根因，确认无真实产品缺陷

- [x] 1.1 阅读 `spec/changes/fix-improve-run-lifecycle-governance/verification-report.md`，复核「真实产品 Bug」根因
  - 结论：父 SPEC 验证报告 17 场景 2 通过 / 15 失败，**15 例失败全部为验证脚手架 mock 层未注入场景专用治理固件所致（伪失败），非 fenixd 产品缺陷**。
    - 后端 `/api/specs?project=fenixd` 过滤正确（56 条真实 spec 来自项目 59 个 SPEC）；dashboard 渲染层健康（`.spec-info-row` 仅当 `error` 非空才渲染、`.alert-item` 无 CSS 隐藏缺陷）；全部 17 场景 `no_console_error` 通过。
    - 治理数据（`governance-*` 行与 `recovery deferred` / `backoff until` / `dispatch_stalled` / `liveness judge unavailable` 文本）缺失，需由验证 `mock_api` 按场景注入固件——属验证基础设施缺陷，依 proposal.md 界定不在本 fix SPEC 范围。
  - 本 SPEC 为 daemon 依据父 SPEC 陈旧 `bug-found` 状态派生的**伪派生 SPEC**；父级已判定「无真实产品 Bug（伪失败排除）」，派生链断裂，**范围内无真实产品缺陷可修复**。

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过
  - 不适用：本仓库无 `package.json`/`tsconfig.json`/`vite`，dashboard 为纯静态资源由 `package.sh` 直接拷贝，无编译步骤。无 TS/前端代码需构建。
- [x] 2.2 运行框架单元测试（`python3 -m pytest tests/ -v`）确认无回归
  - 全量运行 **659 passed**（154.47s）。无 pre-existing failure，无 run-lifecycle 治理相关回归。
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
  - 执行通过（无代码改动，包内容与父 SPEC 一致）。
