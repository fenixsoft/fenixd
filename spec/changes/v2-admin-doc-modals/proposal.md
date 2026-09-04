## Why

呼叫 Admin 按钮需要接通 run-stream 组件的 admin 状态机(等待态→解析 admin_run_id→实时流);SPEC 文档弹窗(需求背景/设计/任务清单三页签懒加载)是列表页文档入口的等价实现(计划 Task 9)。

## What Changes

- 修改 `pages/project.json`:「呼叫 Admin」按钮的占位 toast 替换为 Dialog + RunStream admin 模式接入;「文档」入口接 Dialog + 3 tabs(mountOnEnter 懒加载 /api/spec-doc,doc=proposal|design|tasks)
- 新增 tests/v2/admin-doc.spec.js

## Capabilities

### New Capabilities
- `v2-admin-doc-modals`: Admin 处置弹窗接线 + SPEC 文档弹窗

### Modified Capabilities
- `v2-project-list-page`: 行内「呼叫 Admin」与「文档」入口从占位变为真实弹窗(不改列表本身行为)

## Impact

- 仅改 pages/project.json 与测试;依赖 v2-run-stream-modal
