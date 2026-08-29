## Why

SPEC 列表是 dashboard 的核心工作面:8 列表格、三项过滤、fix- 前缀树形分组、行内操作(呼叫 Admin/调优先级/删除)。v2 以 CRUD + 树行 + dropdown 实现功能等价(形态可变:右键菜单→行内下拉,hover Why→点击懒加载,设计 §4)。

## What Changes

- 新增 `core/dashboard/static/v2/pages/project.json`:crud(spec-crud)拉 /api/specs?project=,adapters.adaptSpecs 排序+树;8 列(状态 mapping、名称链接→#/spec/...、优先级、创建时间、任务进度、验证、耗时、文档);filter 三项(submitOnChange);行内 dropdown-button 三操作;详情 Dialog 懒加载 error/why + 清除错误
- 新增 tests/v2/project.spec.js

## Capabilities

### New Capabilities
- `v2-project-list-page`: SPEC 列表页(8 列/过滤/fix 树/行内操作/error 处理)

### Modified Capabilities

## Impact

- 新增 pages/project.json 与测试;不改其他文件
- 依赖:v2-data-adapters、v2-shell-hash-router、v2-sse-bridge
