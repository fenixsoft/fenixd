## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `spec/changes/improve-agent-config-and-verify-resume/verification-report.md`，定位「真实产品 Bug」的根因并修复

## 2. 验证与打包

- [x] 2.1 运行构建（本仓库为纯 Python + 静态资源，无 npm 构建步骤；`node --check` 校验前端改动）确认通过
- [x] 2.2 运行框架单元测试（`python3 -m pytest tests/ -q`）确认无回归（408 passed）
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
