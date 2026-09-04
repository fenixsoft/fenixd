# Tasks: 修复 fix-worktree-spec-seeding 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `spec/changes/fix-worktree-spec-seeding/verification-report.md`，定位「真实产品 Bug」的根因并修复

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过（不适用：前端为原生 JS，无需构建）
- [x] 2.2 运行框架单元测试（`python3 -m pytest tests/ -v`）确认无回归
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包（不适用：项目无 package.sh 脚本）
