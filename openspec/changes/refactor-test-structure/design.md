# Design: refactor-test-structure

## Context

tests/ 共 18,838 行 27+ 文件，test_core.py（6,700 行）与 test_dashboard.py（2,148 行）是巨型文件，全量 913 用例约 233 秒。refactor-core-packages 已把 core 拆为组件包，refactor-test-callsites 已把测试调用点迁移为组件直调。本 change 重组测试结构并建立"修改文件 → 相关测试"的增量选择能力，缩短 SPEC 实现-验证循环。

前置依赖（STATE.md depends_on 已声明）：refactor-core-packages 与 refactor-test-callsites 均达终态。

## Goals / Non-Goals

**Goals:**
- test_core.py / test_dashboard.py 按主题拆为多个测试模块，单文件回到与 core 组件对应的粒度
- `bin/test_for.py <修改的文件...>`：秒级圈定受影响测试并运行
- 全量入口保留，增量结果可叠加校验
- 拆分前后全量测试结果一致

**Non-Goals:**
- 不改被测代码、不改测试用例的断言与场景逻辑
- 不追求 100% 精确的影响面推导（import 分析 + 映射表的召回率目标：不漏直接依赖；间接耦合由映射表兜底）
- 不引入外部测试选择插件（pytest-testmon 等），纯标准库实现

## Decisions

### D1: 拆分粒度 = core 组件对齐

test_core.py 按被测对象拆分，命名 `test_<组件>.py`：
- PMEngine 侧：test_pm_dispatch.py（队列/老化/退避）、test_pm_family.py、test_pm_budget.py、test_pm_verification.py、test_pm_recovery.py、test_pm_reporting.py
- AgentRunner 侧：test_runner_prompt.py、test_runner_provider.py、test_runner_liveness.py、test_runner_token.py、test_runner_v2.py
- 平台侧：test_state_machine.py、test_config.py、test_event_bus.py
test_dashboard.py 拆为 test_dashboard_api.py / test_dashboard_data.py / test_dashboard_watcher.py（按被测模块）。
实施时以实际类/方法归属微调清单；无归属争议的小用例就近归入主题最相近的模块。

### D2: 拆分操作纪律（语义等价）

- 夹具/helper：被多个新模块使用的提入 `tests/helpers.py`（或保留在首个使用处并 import）；单模块私有的随用例走。
- 只做"整类/整函数搬移 + import 调整"，禁止顺手改断言、改夹具逻辑、改用例名（除类/函数所在文件外）。
- 每拆一个新模块：该模块 pytest 单跑通过 + 全量 pytest 用例数与结果与拆分前一致（用 `pytest --collect-only -q | wc -l` 校验用例数守恒）。
- 每个新模块独立 commit，可单独回滚。

### D3: 增量选择机制 = import 链 AST 推导 + 显式映射补充

**`bin/test_for.py` 契约**：
```
python3 bin/test_for.py core/pm_engine/dispatch.py           # 推导并运行受影响测试
python3 bin/test_for.py --dry-run core/agent_runner/runner.py  # 只列出测试不运行
python3 bin/test_for.py --all                                 # 等价全量
```

**推导算法**（纯标准库 ast 模块）：
1. 输入文件 → 规范化为模块路径（如 core.pm_engine.dispatch）。
2. 扫描 tests/**/*.py 的 import 语句（ast.Import / ast.ImportFrom，含函数内局部 import——test_core.py 大量在测试函数内 import），建立 测试文件 → 依赖模块集合 映射。
3. 若测试文件直接 import 目标模块 → 命中；否则沿 import 闭包传递推导（目标模块被 core/X import，测试 import core/X → 命中），传递深度上限 3 层控制开销。
4. 映射表 `tests/test_map.yaml` 追加无法从 import 推导的耦合：键为文件路径或前缀，值为测试文件/用例 glob。示例：dashboard 静态资源 → test_dashboard_api.py；STATE.md 格式 → test_core.py 中的状态机用例。
5. 汇总去重后输出 `pytest <tests...>` 并运行；无命中时明确提示回退全量。

**映射表格式**（YAML，与仓库既有 YAML 配置风格一致）：
```yaml
# tests/test_map.yaml — import 分析覆盖不到的间接耦合
explicit:
  "core/dashboard/static/": "tests/test_dashboard_api.py"
  "STATE.md": "tests/test_state_machine.py"
```

### D4: 全量校验锚点

增量选择存在漏召风险，因此：实现期每个拆分 commit 必须全量 pytest 守恒验证；日常开发中增量跑绿后、SPEC 的 verify 阶段仍跑全量（框架既有流程不变）。增量入口是加速器，不是全量的替代。

## Risks / Trade-offs

- [AST 推导漏掉动态引用（字符串路径 import、monkeypatch 目标）] → 映射表兜底 + verify 阶段全量锚点；推导器对无法解析的 import 忽略并在 --dry-run 提示覆盖率。
- [拆分时夹具遗漏导致用例失败] → 每个新模块独立 commit + 单跑验证；用例数守恒校验防丢用例。
- [test_map.yaml 腐化（改结构后映射失效）] → test_for.py 启动时校验映射指向的测试文件存在，失效映射告警。
- [测试 ID 变化影响既有习惯] → 无 CI/外部系统引用测试 ID；仓库内无按测试 ID 过滤的脚本（已确认），风险可接受。

## Migration Plan

顺序：先拆 test_core.py（多个 commit）→ 拆 test_dashboard.py → 建 bin/test_for.py 与映射表 → 全量对比验证。回滚粒度为单个新测试模块的 commit。无数据迁移。

## Open Questions

无。
