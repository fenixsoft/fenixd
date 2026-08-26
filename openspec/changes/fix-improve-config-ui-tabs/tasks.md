# Tasks: 修复 improve-config-ui-tabs 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/improve-config-ui-tabs/verification-report.md`，定位「真实产品 Bug」的根因并修复（报告缺失；根因经核查为 improve-config-ui-tabs 特性（页签化 + Administrator 分配）从未合入代码）

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过（本仓库无前端构建步骤，app.js 为原生 JS；已用 `node --check` 校验语法）
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归（`.fenix/tests/` 路径不存在，已运行 `tests/` 全量 400 通过）
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
