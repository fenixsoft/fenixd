# Design: refactor-test-callsites

## Context

refactor-core-packages 拆包后，PMEngine/AgentRunner 以门面模式保留一行委托方法（`def _process_queue(self): self._dispatcher.process_queue()`），使现有测试零修改通过。该委托层为临时兼容层，约 40+ 方法，掩盖真实组件边界。本 change 在拆包完成后迁移测试调用点并收缩门面。

前置条件：refactor-core-packages 达到 implemented/verified 状态（STATE.md `depends_on` 已声明，daemon 自动等待）。

## Goals / Non-Goals

**Goals:**
- tests/ 全部门面委托调用点改写为组件直调
- 删除测试不再引用的委托方法，门面回归"组装 + 生产编排"职责
- 全量测试结果不劣于基线

**Non-Goals:**
- 不修改测试用例的断言语义、夹具构造、场景预期（纯调用点改写）
- 不拆分测试文件（refactor-test-structure 负责）
- 不动组件内部实现

## Decisions

### D1: 直调目标按拆包最终形态确定

迁移以 refactor-core-packages 交付后的实际组件命名为准（engine._dispatcher / engine._family / engine._budget / engine._verification / engine._recovery / engine._reporting；runner._prompt_builder / runner._provider_circuit / runner._liveness / runner._token_budget / runner._v2_server 等）。若实现期组件归属与设计有出入，以代码现状为准，不回改拆包 SPEC。

### D2: 门面收缩规则

- **删**：仅被测试引用的一行委托方法，迁移完成后删除。
- **留**：门面上有生产调用者的方法（fenixd.py、core/dashboard、事件回调编排）一律保留，即使测试也引用。
- **判据**：grep 全仓库（core/ + fenixd.py + tests/ + bin/）确认零调用者后才删除。

### D3: 分文件分批迁移

按测试文件分批：每批一个 commit，批内"改写调用点 → 该文件 pytest 通过 → 全量 pytest 通过"。批顺序按耦合面从小到大（单组件测试文件先迁，test_core.py 最后）。禁止跨批混入其他改动。

### D4: 语义等价验证

迁移不改断言。验证三层：批内改写文件的 pytest 单跑通过；全量 pytest 不引入新失败（基线 912 passed + 1 环境性失败）；grep 确认 tests/ 中不再有指向已删委托的调用。

## Risks / Trade-offs

- [测试触达私有实现，组件重构后测试更显脆弱] → 这是本 change 的已知取舍：直调使测试紧贴组件真实边界，比隔着委托层更诚实；后续组件内部重构时同步改测试调用点。
- [门面委托删除遗漏导致测试引用 AttributeError] → D2 的 grep 全仓库判据 + 每批全量 pytest 兜底。
- [迁移中误改断言语义] → diff 审查纪律：批内 diff 应只含调用点改写，出现断言行改动即回退重做。

## Migration Plan

分批 commit 逐文件迁移，全部完成后单独 commit 收缩门面，最后全量验证。回滚粒度为批。无数据迁移。

## Open Questions

无——依赖 SPEC（refactor-core-packages）完成后，组件命名即为既成事实。
