# Tasks: 修复 improve-run-lifecycle-governance 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `spec/changes/improve-run-lifecycle-governance/verification-report.md`，定位「真实产品 Bug」的根因并修复

## 2. 验证与打包

- [x] 2.1 运行 `npm run build`（项目为原生 Python/JS，无前端构建步骤；以 `python3 -m pytest tests/ -q` 编译级验证替代）→ 695 passed，无回归
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）→ 695 passed，无回归
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
