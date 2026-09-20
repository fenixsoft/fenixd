## Why

代码审查发现问题修复 SPEC（由 code-review 台账选中条目机械生成）。

选中条目（`.fenix/code-review/items.jsonl`，`item_id=bd14491bfae6`，`status=in_spec`）：

- `core/agent_runner/liveness.py:996` — `float() 直接转换运行超时可能抛 TypeError`
  （severity: minor）。原描述称「`runner` 不可用 / 异常被吞后 `ConfigLoader` 也回退失败」
  会给 `float(None)` 抛 `TypeError`——评审阶段实测**部分证伪**：
  `ConfigLoader.effective_run_timeout_seconds` 的每个分支都返回 float
  （`core/config.py:1599-1606`），该路径不会返回 `None`；真正的可达路径是
  **门面本身返回 `None`**（`self._pm._effective_run_timeout(...)` 为替身/最小门面形态，
  同段 `liveness.py:1022-1026` 已显式承认「门面可能不暴露 config」），
  以及 `config` 非 dict 时 `ConfigLoader.normalize_timeout_overrides`
  在 `config.get` 上抛 `AttributeError`（实测：`config=None` → `config.py:1548`）。
  两者都会让整个 deadline 判定崩溃并向 `_run_claude` 轮询环冒泡。

本 SPEC 的定位因此明确为**纵深防御硬化**（把监督主路径的一次判定崩溃，改为兜底值 +
WARNING 后继续判定），而非修复在飞缺陷——生产装配（`fenixd.py:213` → `:285`）恒传
dict config 且门面恒返回 float，今日该路径不可达。

## What Changes

- 修复以下审查发现（SPEC `fix-cr-robustness`）：

  - [minor] float() 直接转换运行超时可能抛 TypeError（core/agent_runner/liveness.py:996）

- 硬化内容：`_supervision_deadline_action` 的 `run_timeout` 解析增加数值校验与
  `try/except` 兜底，兜底值取 `core.config.RUN_TIMEOUT_FALLBACK_SECONDS`（单一来源，
  禁止手写字面量），并在兜底时打 WARNING——详见 design D1。
- 配套回归测试：新增 `tests/test_liveness_hang_discrimination.py` 两个用例
  （门面返回 `None` / 门面抛异常），见 design D2。

## Capabilities

### New Capabilities

- 修复 code-review 台账中选中的代码质量问题。

## Impact

- 修改 `## Deliverables` 声明段所列文件（`core/agent_runner/liveness.py`、
  `tests/test_liveness_hang_discrimination.py`）。

## Non-Goals

- MUST NOT 改动 `core/config.py`（`effective_run_timeout_seconds` 的返回契约已是 float，
  不为其增设第二套兜底）。
- MUST NOT 在本 SPEC 内订正 `core/agent_runner/runner.py:3325` / `:3847` 两处
  「回退 3600」的过期 docstring（实现常量是 `RUN_TIMEOUT_FALLBACK_SECONDS`=9000，
  `core/config.py:25`）——属文档口径问题，独立记账，避免触及未声明的行号漂移面。
- 正常路径（门面返回有效数值）的 `run_timeout`、派生 `absolute_max` 与 ERROR 文案
  数值 MUST 逐位不变。
- MUST NOT 把修复扩面到同一函数内 judge LLM 活性判定段（`liveness.py:1068+` 的
  `_judge_liveness` 调用无 try/except，异常同样会冒泡）——属独立问题、独立记账；
  本 SPEC 只硬化 `run_timeout` 解析这一条路径。
