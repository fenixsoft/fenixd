# Tasks: 修复 add-parallelism 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 定位「严格优先级调度」的产品 Bug 并修复：高优先级任务等待时，低优先级运行档不应继续补齐并行度

## 2. 验证与打包

- [x] 2.1 纯 Python 项目，无前端构建步骤（跳过 npm build）
- [x] 2.2 运行框架单元测试（`python3 -m pytest tests/ -v`）确认 142 个测试全部通过
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
