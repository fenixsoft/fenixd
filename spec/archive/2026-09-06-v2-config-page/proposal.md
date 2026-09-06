## Why

配置页是表单最重的页面:5 页签(LLM Provider 卡片+env KV、Agent 链编辑器可排序、并行度 4 项、审批模式、主题只读说明)。v2 用 Form + input-array/combo 实现,保存走 buildConfigPayload 三级回退合并(behavior.md §6)。关键约束:config 页编辑中必须豁免任何 SSE 触发的 reload,否则会吞表单输入(behavior.md §0/§9)。

## What Changes

- 新增 `core/dashboard/static/v2/pages/config.json`:config-loader service(拉初始值,写 window.__configSnapshot)+ form(config-form)5 页签;提交 requestAdaptor 调 buildConfigPayload;保存成功 toast
- config 页不监听任何 sse:* 广播(编辑豁免)
- 新增 tests/v2/config.spec.js

## Capabilities

### New Capabilities
- `v2-config-page`: 配置页(5 页签/链编辑器/三级回退/编辑豁免)

### Modified Capabilities

## Impact

- 新增 pages/config.json 与测试;依赖 v2-data-adapters
- 保存端点为老版同款 POST /api/config,请求体形态 behavior.md §6
