# Tasks: 修复 add-spec-context-menu 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/add-spec-context-menu/verification-report.md`，定位「真实产品 Bug」的根因并修复

## 2. 验证与打包

- [x] 2.1 运行 `node --check` 校验前端构建（无 npm 打包步骤，纯静态 JS）+ 全量 pytest 无语法/编译错误
- [x] 2.2 运行框架单元测试（`python3 -m pytest tests/ -v`，626 passed）确认无回归
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
