# Design: frozen-scenario-contract-versioning

## D1: contract_version 字段与冻结文件格式

冻结场景文件（test_scenarios.json）**根节点维持 JSON 数组**——读端 `load_scenarios`（core/verify_engine/scenarios.py:973）与 `_load_frozen_scenarios`（core/pm_engine/verification/scenario_gate.py:597）都只接受数组，改根节点形态会撞坏全部读端与写端（`save_scenario_set` / `_scenarios_full.json` 备份 / `_apply_scenario_freeze`）。版本标记落在**条目级**，与既有 `schema_version` 同层：

```json
[
  {"id": "...", "kind": "web", "schema_version": 1, "contract_version": 1,
   "steps": [...], "assertions": [...]}
]
```

- `contract_version`：整型，标识该条目/该冻结集所符合的场景验收契约规则版本。**缺失或非整型 → 视为 1**（存量兼容，与既有 `_schema_version_notes` / `migrate_scenario_schema` 的条目级字段口径一致）。
- `CONTRACT_VERSION_FIELD = "contract_version"`、`CURRENT_CONTRACT_VERSION = 2`：常量定义于 core/verify_engine/scenarios.py 词表区（该文件是场景模型的唯一权威源）。v2 = 「web 场景 MUST 含 navigate 步骤（绝对 URL）」。
- 写端：`prepare_scenarios_for_write`（core/verify_engine/scenarios.py:95，全部写盘路径共用）额外恒定盖 `contract_version = CURRENT_CONTRACT_VERSION` 戳——**新建/冻结写回的文件天然是当前契约版本，下轮加载零迁移、不产生「新产场景被判旧契约」副作用**。
- v1 集合的版本取条目级最大/最小值口径：冻结集按统一生成批次落盘，条目版本不一致本身即异常，取 **min** 迁移（保守：任一旧条目都走迁移），实现时以 `min` 判定、以全部条目盖戳。

## D2: 契约迁移逻辑

### D2.1 迁移函数签名

```python
# core/verify_engine/scenarios.py
def migrate_frozen_contract(
    scenarios: list,
    current_version: int = CURRENT_CONTRACT_VERSION,
    base_url: str = "",
) -> dict:
    """迁移冻结场景集到当前契约版本。

    Returns: {'migrated': list, 'pending_replan': list, 'aborted': str}
      migrated: 已迁移（含版本戳）的场景 dict 列表（已剔除无法迁移项）
      pending_replan: 无法机械迁移的场景 id 列表
      aborted: 迁移后 migrated 为空时取值 'all_scenarios_stale'，否则 ''
    """
```

- 纯函数、不读不写盘；`base_url` 由调用方注入（**不反向依赖 pm_engine 门面**——scenarios.py 属引擎层，不得 import pm_engine）。
- `migrate_frozen_contract` 不写版本戳落盘职责，只返回内存结果；落盘由 pipeline 调用点决定（D2.3）。

### D2.2 v1→v2 迁移（navigate 补齐）

对 `contract_version < 2` 的冻结集逐场景处理：

1. **非 web 场景**（`kind` ∈ {cli, api}）：无需 navigate 规则 → 原样保留，仅盖 `contract_version = 2`。
2. **web 场景且已有 navigate 步骤**：仅盖 `contract_version = 2`（不重复插入、不改 navigate 既有字段）。
3. **web 场景缺 navigate**：
   - 候选 URL 取值顺序（唯一确定、可测）：
     a. 场景内已有 step 的 `url` 字段（api 形态残留 / 手写场景），取首个 `^https?://\S+$`；
     b. 否则取并入参 `base_url`（引擎契约供给的被测实例基址，serving.py:462 `_current_instance_base_url` 的语义：static 契约 server.base_url、否则 `{env:BASE_URL}`）；
     c. 再否则（base_url 为空）→ 该场景移入 `pending_replan`，从迁移结果剔除。
   - **MUST NOT 从 steps 文本正则挖 URL**：web 场景不含 `run` 步骤（`CLI_ACTIONS = {"run"}`，web 场景带 run 本身即校验错误），navigate 目标 URL 的权威载体是步骤 `value` 字段（serving.py:578-579）；`click/type` 的 `target`/`value` 是选择器与输入值，正则命中即为误取。
   - 命中候选 URL 后生成 `{"action": "navigate", "value": <url>, "description": "契约 v2 自动补齐（navigate 绝对 URL）"}`，**插入 steps 首位**（与「web 场景先打开页面再交互」语义一致，且保证 `_current_instance_base_url` / 可达性探测的步骤扫描顺序不变）；同时盖 `contract_version = 2`。

### D2.3 迁移函数调用点（pipeline.py）

`_load_frozen_or_escalate`（pipeline.py:941）改造后的顺序（**顺序是本设计的关键约束**）：

1. 读冻结文件原始 JSON（数组），得 `raw`（未过 `load_scenarios`）；文件不存在 → 返回 `(None, False)` 走既有出题通道（行为不变）；文件不可解析（JSON 语法错）→ 沿用既有 corrupt → env_blocked（不属契约漂移，维持人工）。
2. 取集内 `contract_version` 的 min 值判定（缺失/非整型 = 1）。
3. `min < CURRENT_CONTRACT_VERSION` → 取 `base_url = self._current_instance_base_url(spec_name)`，调用 `migrate_frozen_contract(raw, base_url=base_url)`。
   - 迁移前 MUST 备份原文件（`test_scenarios.json.contract-v1.bak`，与回退口 D4 配套）；
   - 迁移后把 `{'migrated': ...}` 写回冻结文件（JSON 数组，含 `schema_version` 与 `contract_version` 戳）——写回失败 ERROR 留痕并**照常以内存中的迁移结果继续**（不因写盘失败退回 corrupt；下次加载再迁一次即幂等）。
   - `aborted = 'all_scenarios_stale'`（`migrated` 为空）→ 见 D3。
   - 部分迁移（`pending_replan` 非空且非全量）→ WARNING 留痕列出 id，被剔除场景不参与本轮，剩余场景继续。
4. 迁移完成（或无需迁移）后，以最终场景集走既有验收：`load_scenarios(path)`（读盘，即写回后的文件）。
   - 同时把迁移结果回注 `self._frozen_migrated`（实例属性，供阶段1 复用分支的 diff 基线使用，见 D4 风险 4）。
5. 验收仍失败 → 沿用既有 corrupt → env_blocked（人工裁决），**且** 在告警正文中给出回退指引：删除 `test_scenarios.json.contract-v1.bak` 后由人工/下一轮恢复原集（否则迁移后的文件已覆盖原文件，人工看不到「原始集」）。
   - 未被迁移（`contract_version >= 2`）且验收失败 → 完全维持现状（不备份、不写回，告警文案不变）。

## D3: 全场景过时处理（aborted → 本轮回落出题通道）

当 `migrate_frozen_contract` 返回 `aborted = 'all_scenarios_stale'`（全部场景无法定位 URL）：

1. **不置 blocked / env_blocked**、不升级人工。
2. 删除 `test_scenarios.json`（即既有 admin 处置选项①的机械版），并**本轮回落到出题分支**：`_load_frozen_or_escalate` 返回 `(None, False)`，主循环随即以 `frozen=None` 进入 `_run_three_stage_verification` 既有的 planner 出题通道（pipeline.py:1450-1520），**不动主循环控制流**（MUST NOT 在 `_load_frozen_or_escalate` 内递归调用 `_run_three_stage_verification`）。
3. INFO 日志：「契约升级全场景过时、已自动重新出题，旧场景数=XX，旧 contract_version=1」。
4. 重出题产物由写端（`prepare_scenarios_for_write` / `_apply_scenario_freeze`）盖当前 contract_version 戳，下轮起零迁移；本轮回退不再有「旧集被验收判 corrupt」的窗口。
5. 重出题仍受既有 replan 预算（`replan_left = 2`）与空集兜底（`{'aborted': 'no_valid_scenarios'}`）约束——本设计不新增、不绕开这些闸门。

## D4: 迁移安全性约束与风险处置

- **幂等**：`contract_version >= CURRENT_CONTRACT_VERSION` 时零操作（不迁移、不写回、不备份）——D1 的写端盖戳保证新文件天然达标。
- **最小改动**：只插入 navigate 步骤 + 盖版本戳；不改命令/断言/其他字段，不动步骤顺序（除首位插入）。
- **写回原子性**：写回使用 `path.write_text` 前落盘临时文件后替换（或沿用同目录 `write_text` + 异常捕获）；写回失败不改变本轮内存结果，仅 ERROR 留痕。
- **可回退（备份）**：迁移前备份原文件为 `test_scenarios.json.contract-v1.bak`（同目录、下轮加载忽略该名），为「迁移结果不合预期」保留人工恢复路径；备份随下次成功迁移覆盖（只留最近一版）。
- **迁移后二次验收失败**（合成 navigate 可能仍不满足其他规则，如 URL 无端口/主机非法）：走既有 corrupt → env_blocked，并在处置选项文本中新增第③条「如需恢复迁移前集合：删除 `test_scenarios.json` 与 `test_scenarios.json.contract-v1.bak` 的对应项后由 planner 重出题 / 或把 `.bak` 恢复为原文件」。**MUST NOT 把「迁移后仍失败」静默吞掉或再自动重出题**（可能掩盖真实场景缺陷）。
- **与冻结复用分支的一致性**：迁移后本轮场景集与上一轮冻结集不同（可能少若干待重排场景、多若干 navigate 步骤），阶段1 复用分支的 diff 基线改用迁移结果（`self._frozen_migrated`），避免把「迁移」误记为「planner 本轮凭空增改场景」。
- **日志与审计（spec R3）**：每次迁移 MUST 写 INFO：场景总数、成功迁移数（补齐 navigate）、移除过时数、contract_version 变更（1→2）；`pending_replan` 移除项写 WARNING 并附 id 列表。

## D5: 多版本迁移链（spec R4）

- 迁移逻辑按版本号登记：`_CONTRACT_MIGRATIONS = {2: _migrate_contract_to_v2}`，`_migrate_contract_to_v2(scenarios, base_url)` 只负责「1 → 2」这一步。
- `migrate_frozen_contract` 用 `while current < CURRENT_CONTRACT_VERSION: current = _apply_next_migration(...)` 循环推进，**支持跳版本**（v1 直迁 v3 = 依次执行 2、3 两段逻辑，前段产物直接喂后段）。
- 未登记的版本段（`current + 1 not in _CONTRACT_MIGRATIONS`）→ 返回 `aborted = 'no_migration_path'`，**回退到既有 corrupt → env_blocked 人工通道**（fail-closed：不猜、不跳过）。
- 未来新增 v3 时只需追加一个函数 + 一个登记项；`CURRENT_CONTRACT_VERSION` 递增。

## D6: 测试策略

tests/test_frozen_contract_evolution.py（新建，纯函数 + pipeline 调用点两级）：

- `migrate_frozen_contract` 纯函数级（无 IO、无需 verify server）：
  - (a) v1 web 场景缺 navigate + 提供 base_url → 生成 navigate 步骤（**字段为 `value`**）、插入首位、`contract_version=2`，且迁移结果过 `validate_scenario_dicts`；
  - (b) web 场景 steps 含 `run` + command 内 URL 但无 navigate → 不被当作 URL 来源（不挖文本），改用 base_url；
  - (c) base_url 为空且场景无 url 字段 → 场景进 `pending_replan`，其余场景照常迁移；
  - (d) 全部场景进 `pending_replan` → `aborted='all_scenarios_stale'`、`migrated` 为空；
  - (e) 已有 navigate 的 web 场景 / cli / api 场景 → 只盖版本戳、步骤零变化；
  - (f) 幂等：`contract_version=2` 的集合 → 零操作（返回原集合、无写回标志）；
  - (g) 空集合 → `aborted='all_scenarios_stale'`（与「全量过时」同语义）；
  - (h) 跳版本：`CURRENT_CONTRACT_VERSION=3` 时 v1 集走两段迁移（登记表含 v2、v3 测试桩）与未登记版本段 → `aborted='no_migration_path'`。
- pipeline 调用点级（mock 冻结文件 + patch `_current_instance_base_url` / 写回路径）：
  - (i) v1 冻结文件加载 → 迁移 + 写回后 `contract_version=2` 持久化、备份 `test_scenarios.json.contract-v1.bak` 存在；
  - (j) 全过时 → `_load_frozen_or_escalate` 返回 `(None, False)` 且冻结文件被删除、**未调用 `_escalate_env_blocked`**；
  - (k) 写端回归：`prepare_scenarios_for_write` 盖 `contract_version` 戳（新文件不被判旧契约）。
