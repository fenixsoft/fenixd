# test-incremental-selection 规格

## ADDED Requirements

### Requirement: 巨型测试文件按主题拆分

test_core.py（6,700 行）与 test_dashboard.py（2,148 行）MUST 按被测对象拆分为多个测试模块（拆分清单以 design D1 为准，实施时按实际归属微调）；拆分后单文件 SHOULD 回到与 core 组件对应的粒度。拆分 MUST 只做整类/整函数搬移与 import 调整，MUST NOT 修改断言、夹具逻辑或用例语义；共享夹具/helper MUST 归位（多模块共用的提入 tests/helpers.py）。

#### Scenario: 用例数守恒

- **WHEN** 每个新测试模块拆出后运行 `pytest --collect-only -q` 统计用例数
- **THEN** 用例数与拆分前基线一致（无丢失、无新增），全量 pytest 结果不劣于基线

#### Scenario: 拆分 diff 纪律

- **WHEN** 审查任一拆分 commit 的 diff
- **THEN** diff 仅含用例/夹具搬移与 import 调整，不含断言值或场景逻辑修改

### Requirement: 增量测试选择入口

仓库 MUST 提供 `bin/test_for.py`：接受一个或多个修改文件的路径，通过 AST 解析 tests/ 的 import 链（含测试函数内局部 import）自动推导受影响测试并运行；支持 `--dry-run`（只列出测试）与 `--all`（等价全量）。推导 MUST 为纯标准库实现（ast 模块），MUST NOT 引入外部测试选择插件。

#### Scenario: 直接依赖命中

- **WHEN** 运行 `bin/test_for.py --dry-run core/pm_engine/dispatch.py`（该模块被某测试文件直接 import）
- **THEN** 输出包含该测试文件，且运行模式下单跑全绿

#### Scenario: 传递依赖命中

- **WHEN** 测试 import core/X 而目标模块 core/Y 被 core/X 依赖（传递闭包 ≤3 层）
- **THEN** 该测试同样被选中

#### Scenario: 无命中回退

- **WHEN** 修改文件的受影响测试推导结果为空
- **THEN** 工具明确提示回退全量而非静默通过

### Requirement: 显式映射补充

import 推导覆盖不到的间接耦合 MUST 通过 `tests/test_map.yaml` 显式声明（文件路径/前缀 → 测试文件或用例 glob）；test_for.py 启动时 MUST 校验映射指向的测试文件存在，失效映射 MUST 告警。

#### Scenario: 间接耦合覆盖

- **WHEN** 修改 core/dashboard/static/ 下的静态资源（无 Python import 关系）
- **THEN** test_map.yaml 声明的对应测试被选中运行

#### Scenario: 失效映射告警

- **WHEN** test_map.yaml 中某映射指向的测试文件不存在
- **THEN** test_for.py 启动时输出告警信息

### Requirement: 全量锚点保留

增量选择 MUST NOT 替代全量测试：SPEC 的 verify 阶段仍运行全量 pytest；实现期的每个拆分 commit MUST 通过全量验证（用例数守恒 + 结果不劣于基线 912 passed + 1 环境性失败）。

#### Scenario: verify 阶段全量

- **WHEN** 本 SPEC 实现完成进入 verify 阶段
- **THEN** 全量 pytest 运行且结果不劣于基线

### Requirement: 被测代码零修改

本 change MUST NOT 修改 core/、fenixd.py 等被测代码；改动范围限于 tests/ 结构重组、bin/test_for.py、tests/test_map.yaml。

#### Scenario: 改动范围审计

- **WHEN** 审查本 SPEC 全部 commit 的变更文件清单
- **THEN** 仅含 tests/**、bin/test_for.py、tests/test_map.yaml，无被测代码文件

### Requirement: 依赖前置

本 change MUST 声明 `depends_on: refactor-core-packages,refactor-test-callsites`，两者均达 implemented/verified/done/pushed 前不开始实现。

#### Scenario: daemon 自动等待

- **WHEN** daemon 调度检查本 SPEC 而任一依赖未达终态
- **THEN** 本 SPEC 被跳过派发，日志记录依赖未满足
