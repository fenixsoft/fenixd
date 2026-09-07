# test-callsite-migration 规格

## ADDED Requirements

### Requirement: 调用点组件直调

tests/ 下所有经门面委托访问组件实现的方法调用 MUST 改写为组件直调（如 `engine._process_queue(...)` → `engine._dispatcher.process_queue(...)`、`runner._build_prompt(...)` → `runner._prompt_builder.build(...)`，以 refactor-core-packages 交付后的实际组件命名为准）。改写 MUST 保持断言语义零变化：不修改测试用例的预期值、夹具构造与场景逻辑。

#### Scenario: 迁移后全量测试通过

- **WHEN** 全部测试文件迁移完成并运行全量 pytest
- **THEN** 结果不劣于基线（912 passed + 1 个已认定的环境性失败，不引入新失败）

#### Scenario: 迁移 diff 纪律

- **WHEN** 审查任一迁移批次的 commit diff
- **THEN** diff 仅含测试调用点改写，不含断言值、夹具构造或场景逻辑的修改

### Requirement: 门面收缩

迁移完成后，仅被测试引用的委托方法 MUST 从门面删除；有生产调用者（fenixd.py、core/dashboard、事件回调编排、组件间协作）的方法 MUST 保留。删除判据为全仓库 grep（core/ + fenixd.py + tests/ + bin/）确认零调用者。

#### Scenario: 无死委托

- **WHEN** 门面收缩 commit 后 grep 全仓库检查被删方法名
- **THEN** 无任何代码引用已删除的委托方法，且全量 pytest 通过

#### Scenario: 生产路径零影响

- **WHEN** 门面收缩完成
- **THEN** fenixd.py 与 core/dashboard 的 import 及调用语句无任何修改

### Requirement: 分批迁移与验证

迁移 MUST 按测试文件分批执行：每批独立 commit，批内先改写后验证（该批文件 pytest 单跑通过 + 全量 pytest 通过）；test_core.py 最后迁移；禁止在迁移 commit 中混入其他改动。

#### Scenario: 批次门禁

- **WHEN** 任一迁移批次完成
- **THEN** 该批有独立 commit，commit 时批内文件单跑与全量 pytest 均通过

### Requirement: 依赖前置

本 change MUST 声明 `depends_on: refactor-core-packages`，在其达到 implemented/verified/done/pushed 前不开始实现。

#### Scenario: daemon 自动等待

- **WHEN** daemon 调度检查本 SPEC 而 refactor-core-packages 未达终态
- **THEN** 本 SPEC 被跳过派发，日志记录依赖未满足
