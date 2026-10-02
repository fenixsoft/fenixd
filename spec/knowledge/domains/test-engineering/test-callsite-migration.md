<!-- knowledge: capability=test-callsite-migration rev=1 sources=spec/archive/2026-09-07-refactor-test-callsites -->

# 测试调用点组件直调

tests/ 对 core 组件的访问规则：一律直调组件实现，不经门面委托方法；门面不为测试保留死委托。

## 现行规则

- tests/ 下访问组件实现的方法调用一律组件直调（如 `engine._process_queue(...)` → `engine._dispatcher.process_queue(...)`、`runner._build_prompt(...)` → `runner._prompt_builder.build(...)`，以 refactor-core-packages 交付后的实际组件命名为准），不绕经门面委托。
- 门面不保留仅被测试引用的委托方法：删除判据为全仓库 grep（`core/` + `fenixd.py` + `tests/` + `bin/`）确认零调用者；有生产调用者（fenixd.py、core/dashboard、事件回调编排、组件间协作）的委托方法保留。
- 调用点改写保持断言语义零变化：不修改测试用例的预期值、夹具构造与场景逻辑；生产路径（fenixd.py 与 core/dashboard 的 import 及调用语句）零修改。
- 此类结构性迁移按测试文件分批执行：每批独立 commit，批内先改写后验证（该批文件 pytest 单跑通过 + 全量 pytest 通过），禁止在迁移 commit 中混入其他改动。

## 溯源

- 2026-09-07 refactor-test-callsites（spec/archive/2026-09-07-refactor-test-callsites） — 确立测试调用点组件直调、门面死委托清除与分批迁移验证纪律；迁移后全量 pytest 结果不劣于基线
