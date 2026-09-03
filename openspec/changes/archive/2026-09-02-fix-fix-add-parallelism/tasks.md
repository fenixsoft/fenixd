# Tasks: 修复 add-parallelism 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 修复 ConfigLoader 对 `agents.max_concurrent` / `max_retries` / `max_turns` 强制存在校验的 Bug：字段缺失时应加载成功（消费方取默认值），非法值才拒绝

## 2. 验证与打包

- [x] 2.1 纯 Python 项目，无前端构建步骤（跳过 npm build）
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认 147 个测试全部通过
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包
