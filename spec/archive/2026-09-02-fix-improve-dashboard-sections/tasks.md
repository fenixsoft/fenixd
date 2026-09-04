# Tasks: 修复 improve-dashboard-sections 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `spec/changes/improve-dashboard-sections/verification-report.md`，定位「真实产品 Bug」的根因并修复（注：父 SPEC 的 verification-report.md 在该 worktree 中缺失，无法读取；改为对照 improve-dashboard-sections 的 specs 逐项代码审查，定位并修复一个违背 spec 的真实产品缺陷——fix 树多层嵌套渲染缺失）

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过（静态资源无编译步骤；已用 `node --check` 校验 app.js 语法）
- [x] 2.2 运行框架单元测试（`python3 -m pytest tests/ -q`）确认无回归（377 passed）
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包（dist/fenixd-20260826.tar.gz）
