## Why

替换主入口前的验收闸门:全功能 Playwright 验收脚本 + 深链回归 + 双版并存对比(设计 §7 通过标准:脚本全绿→用户人工过一遍→才允许 cutover)。

## What Changes

- 新增 `tests/v2/acceptance.spec.js`:深链直达(config?tab= / spec/:p/:s,刷新保持)、老版并存冒烟(/ 的 #tl-root 可见)、双版 SPEC 列表行数对齐、run 弹窗三态抽查、admin 弹窗等待态+关闭退订、全程零 pageerror
- 新增 `tests/v2/RUNBOOK.md`:启动命令、fixture 依赖、fixme 用例清单、执行方式

## Capabilities

### New Capabilities
- `v2-acceptance-suite`: 全量验收脚本与运行手册

### Modified Capabilities

## Impact

- 仅新增 tests/v2/ 下文件;依赖全部前序 11 个 SPEC
- 本 SPEC 不改 v2 前端代码;发现缺陷时开 fix spec 回修
