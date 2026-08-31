# Proposal: refactor-test-structure

## Why

测试套件 18,838 行，其中 test_core.py 6,700 行、test_dashboard.py 2,148 行，是增量测试的主要瓶颈：改 core/ 任意一处都要跑完整个 test_core.py（全量 913 用例约 233 秒），拖慢所有 SPEC 的实现-验证循环。测试组织与代码包结构（refactor-core-packages 后的组件粒度）不对应，也无法按修改文件快速圈定测试范围。

## What Changes

- **拆分巨型测试文件**：test_core.py 按主题拆为多个测试模块（PMEngine 派发/family/budget/verification、AgentRunner provider/liveness/token、state_machine/config 等），test_dashboard.py 同样处理；夹具与 helper 随用例归位，测试用例语义零变化。
- **增量测试选择入口**：新增 `bin/test_for.py`——输入修改的文件路径，AST 解析 tests/ 的 import 链自动推导受影响测试并运行；叠加显式映射表（`tests/test_map.yaml`）补充 import 分析覆盖不到的间接耦合（fixture 共享、字符串引用、dashboard 静态资源等）。
- **全量测试保留**：`bin/test_for.py --all` 或直接 pytest 跑全量，增量入口是补充而非替代。
- 本 change 不改任何被测代码。

## Capabilities

### New Capabilities

- `test-incremental-selection`: 按修改文件圈定测试范围的能力——import 链 AST 推导 + 显式映射补充的机制、test_for.py 入口契约、测试文件拆分的组织规则与语义等价保证。

### Modified Capabilities

（无——不改任何既有 spec 级行为要求）

## Impact

- **代码**：tests/ 结构重组（test_core.py 6,700 行 → 多个主题模块；test_dashboard.py 2,148 行 → 若个模块）；新增 bin/test_for.py 与 tests/test_map.yaml。被测代码（core/、fenixd.py）零修改。
- **测试**：拆分前后全量 pytest 用例数与结果一致（912 passed + 1 环境性失败基线）；测试 ID 会随文件移动变化（无 CI/外部系统引用测试 ID，风险已评估为可接受）。
- **依赖**：`depends_on: refactor-core-packages,refactor-test-callsites`——先拆包（组件粒度决定测试主题划分）再迁移调用点（避免测试文件两轮翻动冲突），最后重组测试结构。
