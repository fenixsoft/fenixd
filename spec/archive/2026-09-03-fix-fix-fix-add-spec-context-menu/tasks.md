# Tasks: 修复 add-spec-context-menu 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/add-spec-context-menu/verification-report.md`，定位「真实产品 Bug」的根因并修复（根因结论见 proposal.md「根因结论」：两个 Bug 均为伪失败，产品代码无缺陷，20/20 场景实测通过）

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过（不适用：仓库为纯静态 JS 前端，无 package.json/构建步骤；app.js 直接由 dashboard 服务）
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归（758 passed）
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包（dist/fenixd-20260829.tar.gz）
