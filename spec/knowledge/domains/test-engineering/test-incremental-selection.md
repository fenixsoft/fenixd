<!-- knowledge: capability=test-incremental-selection rev=1 sources=spec/archive/2026-09-08-refactor-test-structure -->

# 测试增量选择

按修改文件推导受影响测试的增量执行入口 `bin/test_for.py`，以及支撑它的测试模块拆分与显式映射规则。

## 现行规则

- 测试模块按被测对象组织：巨型测试文件（test_core.py、test_dashboard.py）按主题拆分为与 core 组件对应粒度的模块；拆分只做整类/整函数搬移与 import 调整，不修改断言、夹具逻辑或用例语义，用例数守恒；多模块共用的夹具/helper 归位 `tests/helpers.py`。
- `bin/test_for.py` 接受一个或多个修改文件路径，经 AST 解析 tests/ 的 import 链（含测试函数内局部 import）自动推导受影响测试并运行；`--dry-run` 只列出测试、`--all` 等价全量；实现为纯标准库（ast 模块），不引入外部测试选择插件。
- 依赖推导覆盖传递闭包 ≤3 层：测试 import core/X 而 core/Y 被 core/X 依赖时该测试同样被选中；推导结果为空时工具明确提示回退全量，不静默通过。
- import 推导覆盖不到的间接耦合经 `tests/test_map.yaml` 显式声明（文件路径/前缀 → 测试文件或用例 glob）；test_for.py 启动时校验映射指向的测试文件存在，失效映射输出告警。
- 增量选择不替代全量：SPEC 的 verify 阶段仍运行全量 pytest；实现期的每个拆分 commit 须通过全量验证（用例数守恒 + 结果不劣于基线）。
- 增量选择与测试结构重组不修改被测代码：改动范围限于 `tests/**`、`bin/test_for.py`、`tests/test_map.yaml`。

## 溯源

- 2026-09-08 refactor-test-structure（spec/archive/2026-09-08-refactor-test-structure） — 新建 AST 推导的增量选择入口与 test_map.yaml 显式映射，完成巨型测试文件按主题拆分（依赖 refactor-core-packages、refactor-test-callsites）
