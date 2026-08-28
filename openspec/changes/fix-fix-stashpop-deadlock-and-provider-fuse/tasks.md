# Tasks: 修复 fix-stashpop-deadlock-and-provider-fuse 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/fix-stashpop-deadlock-and-provider-fuse/verification-report.md`，定位「真实产品 Bug」的根因并修复

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过（本仓库为纯 Python 框架、Dashboard 为原生 JS 直供，无 npm 构建步骤；无 package.json，构建不适用）
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
