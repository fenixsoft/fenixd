# Tasks: 修复 fix-dashboard-duration-and-verify-gate 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/fix-dashboard-duration-and-verify-gate/verification-report.md`，定位「真实产品 Bug」的根因并修复

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过（本仓库为纯 Python 项目无 Node 构建链，前端为直接托管的静态 JS，无需构建；已通过 `python3 -m pytest tests/ -q` 等价验证无回归）
- [x] 2.2 运行框架单元测试（`python3 -m pytest tests/ -v`）确认无回归
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
