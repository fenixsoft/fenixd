# Proposal: refactor-test-callsites

## Why

refactor-core-packages 将 PMEngine/AgentRunner 拆为组合组件后，测试仍通过门面的一行委托方法访问内部实现（如 `engine._process_queue` → `engine._dispatcher.process_queue`）。委托层是临时兼容层：40+ 个委托方法掩盖了真实组件边界，测试无法直接验证组件行为，且每次组件重构都要同步维护委托。应在拆包稳定后立即清理，收缩门面。

## What Changes

- 将 tests/ 中对门面委托私有方法的调用改写为组件直调：`engine._xxx` → `engine._dispatcher.xxx`、`runner._build_prompt` → `runner._prompt_builder.build` 等（按 refactor-core-packages 最终组件命名）。
- 迁移完成后收缩门面：删除不再被任何测试引用的一行委托方法（公共 API 方法与 daemon 生产调用路径保留）。
- 测试断言语义零变化：只改调用点写法，不改测试用例的行为预期；每个测试文件迁移后该文件必须原样通过。
- 分文件迁移，每批独立 commit。

## Capabilities

### New Capabilities

- `test-callsite-migration`: 测试调用点从门面委托到组件直调的迁移方式、门面收缩规则（哪些委托删、哪些留）、迁移的验证策略（语义等价、分批提交）。

### Modified Capabilities

（无——不改任何既有 spec 级行为要求）

## Impact

- **代码**：tests/ 下 27 个测试文件中的调用点改写；core/pm_engine/ 与 core/agent_runner/ 门面的委托方法收缩（仅删除测试不再引用的）。
- **API**：PMEngine/AgentRunner 的公共 API 与生产路径（fenixd.py、dashboard）零变化；被删委托均为测试专用的私有方法。
- **测试**：全量 pytest 结果不劣于基线（912 passed + 1 环境性失败）。
- **依赖**：`depends_on: refactor-core-packages`——组件结构稳定后才能确定直调目标，daemon 会自动等待其完成后才派发本 SPEC。
