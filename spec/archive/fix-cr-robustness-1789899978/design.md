# Design: fix-cr-robustness

## Context

由 code-review 台账选中问题机械生成的修复 SPEC。选中条目（台账 `.fenix/code-review/items.jsonl`，
`item_id=bd14491bfae6`，`status=in_spec`，`spec_name=fix-cr-robustness`）为：

- `core/agent_runner/liveness.py:996` — `float() 直接转换运行超时可能抛 TypeError`（severity: minor）。

取证结论（评审阶段实测）：

- 如实测 `core/agent_runner/liveness.py:996` 的 `run_timeout = float(self._pm._effective_run_timeout(agent_type))`：
  当门面 `_effective_run_timeout` 返回 `None` 时，该行抛出
  `TypeError: float() argument must be a string or a real number, not 'NoneType'`，
  异常向 `_run_claude` 轮询环冒泡 → 被 `core/agent_runner/runner.py:3624` 的
  `except Exception` 捕获并写 `run thread crashed` 终态后 re-raise
  （`core/agent_runner/runner.py:3632`），即「本应续期/终止的一次 deadline 判定」
  升级为整个监督 run 崩溃。
- 生产装配（`fenixd.py:213` → `:285` `AgentRunner(config=...)`）当前恒传 dict，
  且 `ConfigLoader.effective_run_timeout_seconds` 的每个分支都返回 float
  （`core/config.py:1599-1606`），故该 `TypeError` 今日**不可达**；但该行是监督循环
  主路径，且同段 `liveness.py:1022-1026` 已显式承认「门面可能不暴露 config」这一形态
  （config 非 dict 时经回构最小配置兜底），护栏缺口真实存在。本 SPEC 定位为
  纵深防御（defense-in-depth）硬化，非在飞缺陷修复。

## Decisions

### D1 超时兜底取值契约（单一来源，禁止手写常数）

`run_timeout` 取值 MUST 按以下顺序解析，且兜底分支 MUST 复用既有单一来源，MUST NOT
在该行手写字面常数（先例：`evo-supervision-timeout-config-consistency` 已把
`supervision_floor` 的派生收敛为单一实现，并删除 `SUPERVISION_EXTENSION_SECONDS` 等手写常数；
其回归测试 `tests/test_supervision_timeout_consistency.py:215`
`test_no_handwritten_constant_remains` 对 liveness 源码做字面断言）：

1. `raw = self._pm._effective_run_timeout(agent_type)`；
2. `raw` 为 `int`/`float` 且非 `bool` 且 `> 0` → 取 `float(raw)`（生效值，正常路径，
   数值与改造前逐位一致）；
3. 其余（`None` / 非数值 / `bool` / `≤ 0`）→ 回退
   `float(RUN_TIMEOUT_FALLBACK_SECONDS)`（`core/config.py:25`，值 9000；经
   `from core.config import RUN_TIMEOUT_FALLBACK_SECONDS` 引入，**不是**新写的字面量），
   并把该行包装在 `try/except (TypeError, ValueError, AttributeError)` 内，异常同样回退该值；
4. 门面调用本身抛异常（进程表/配置层故障）同样回退该值，不得让异常逃逸出
   `_supervision_deadline_action`。

兜底分支 MUST 打 WARNING 日志（component `agent_runner`，含 `agent_type`、收到的原始
`raw` 值与其 `repr`），保证「门面契约漂移」在日志可归因；MUST NOT 静默吞掉。

> 语义依据：`core/agent_runner/runner.py:3847` 的 `_effective_run_timeout` docstring 与
> `core/agent_runner/runner.py:3325` 的说明均以「全局缺失回退 3600」为口径，而
> `core/config.py:1590` 的实现口径为 `RUN_TIMEOUT_FALLBACK_SECONDS`（9000）。
> 本 SPEC 明确以 `core/config.py` 的实现常量为唯一权威来源（D1.3），
> 以保证 `run_timeout` 与同段 `supervision_floor` 派生所用 `cfg["agents"]["run_timeout_seconds"]`
> 同源；`runner.py` 上述两处过期 docstring 的文字订正**不在本 SPEC 交付范围**
> （属文档口径问题，独立记账，避免触及未声明的行号漂移面）。

### D2 回归测试为配套交付物

本 SPEC 的修复无既有测试可覆盖（`tests/` 内无任何用例驱动 `None` 门面返回）：
现有替身 `tests/test_liveness_hang_discrimination.py:57` 的
`_effective_run_timeout` 返回 3600 常量，`tests/test_supervision_timeout_consistency.py`
经 `_make_minimal_runner`（`:73`）装配真实 `AgentRunner.config`。故测试文件
`tests/test_liveness_hang_discrimination.py` 提升为**交付物**（`kind: modify`），
承载两个新用例（见 tasks.md 1.2）：门面返回 `None` → 不抛异常且按 9000 兜底；
门面抛异常 → 同样兜底。既有用例 MUST 全绿（正常路径数值零变化）。

### D3 验收场景可机械判定

`specs/robustness/spec.md` 的场景 MUST 断言修复后的可观测行为（不抛异常 + 兜底值生效的
证据/log 语义），MUST NOT 依赖「条目不再出现在 code-review open 列表」——该表述与台账
状态机不符：`resolve_snapshot` 只核销 `status == "open"` 的条目且 MUST NOT 触碰
`in_spec`（`core/code_review.py:330-337`、`:353-354`），本条目已为 `in_spec`，
既不会出现在 open 列表，也不会被自动核销。机械生成器模板
（`core/code_review.py:1122-1126`）的该句式在本 SPEC 内替换。
