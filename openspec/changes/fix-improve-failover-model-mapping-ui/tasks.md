# Tasks: 修复 improve-failover-model-mapping-ui 验证发现的缺陷

## 1. 修复真实产品缺陷

- [x] 1.1 阅读 `openspec/changes/improve-failover-model-mapping-ui/verification-report.md`（缺失，改读 .fenix/verify-progress 的 report.json），定位「真实产品 Bug」的根因并修复：
  - 链编辑器 `.agent-assign-card` / `.chain-row` / `.btn-add-chain` 位于默认 hidden 的 `agent-models` 标签页，深链 `#config=fenixd` 无法触达（验证 9 场景全失败根因）；为 `parseHash` 增加 `tab` 深链参数并在 `hydrateConfigPage` 加载时按 `currentState.tab` 激活对应页签（`#config=fenixd&tab=agent-models` 直达）。
  - 添加 Provider 行点击处理器引用未定义变量 `providers`（仅 `renderConfig` 作用域内的 const），点击「+ 添加 Provider 行」时抛 ReferenceError；改用 `readProviderCards()` 在点击时读取当前 provider 列表。

## 2. 验证与打包

- [x] 2.1 构建校验：本项目为 Python + 静态 JS（无 package.json / tsc / vite），`node --check core/dashboard/static/app.js` 语法通过；打包脚本 `scripts/package.sh` 生成的 tar.gz 含修复后的 app.js（已 grep 确认 `currentState.tab` 存在）。
- [x] 2.2 运行框架单元测试（`python3 -m pytest tests/ -v`，实际测试目录为 `tests/`）确认无回归：626 passed。
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包：`dist/fenixd-20260828.tar.gz`（324K）。
