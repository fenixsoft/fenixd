# Tasks: 修复 improve-agent-config-and-verify-resume 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `spec/changes/improve-agent-config-and-verify-resume/verification-report.md`，定位「真实产品 Bug」的根因并修复

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过（本项目为纯 JS/Python，无 tsc/vite；以 `node --check` 校验前端改动通过）
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
