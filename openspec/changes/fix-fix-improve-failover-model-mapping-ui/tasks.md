# Tasks: 修复 fix-improve-failover-model-mapping-ui 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/fix-improve-failover-model-mapping-ui/verification-report.md`，定位「真实产品 Bug」的根因并修复

## 2. 验证与打包

- [x] 2.1 运行构建确认编译通过（本项目 Dashboard 为原生 JS/CSS 无 tsc+vite 构建步骤；app.js 语法校验通过）
- [x] 2.2 运行框架单元测试（`python3 -m pytest tests/` 等价项）确认无回归：659 passed
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包（dist/fenixd-20260828.tar.gz）
