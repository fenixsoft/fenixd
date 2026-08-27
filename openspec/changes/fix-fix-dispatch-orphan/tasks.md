# Tasks: 修复 fix-dispatch-orphan 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/fix-dispatch-orphan/verification-report.md`，定位「真实产品 Bug」的根因并修复

## 2. 验证与打包

- [x] 2.1 前端为原生 JS（无 tsc/vite 构建步骤）；npm run build 不适用，框架无需编译构建
- [x] 2.2 运行框架单元测试（`python3 -m pytest tests/ -q`）确认无回归（367 passed）
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包（fenixd-20260827.tar.gz）
