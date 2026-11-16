# design — judge 原地修复写回受理门（fail-closed 整批校验 + 成对落盘）

## 1. 现状链路（已核实）

judge 原地修复（judge-scenario-repair 通道）现状写回与受理链路：

1. **直改写回**：`agents/planner-judge.md:145` 原地修复协议第 1 步指示 judge 直接修改
   `{scenarios_path}`（`.fenix/verify-progress/<spec>/test_scenarios.json`）——写入瞬间无任何校验。
2. **申报受理**：judge 申报 `{"status": "scenario-repaired", ...}` 后，框架
   `_handle_scenario_repaired`（`core/pm_engine/verification/pipeline.py:1855`）依次：
   预算检查（`_SCENARIO_REPAIR_MAX_ROUNDS`，耗尽两态处置）→ 受理门（耗尽持久态拒收，
   `pipeline.py:1955-1976`）→ `_apply_scenario_freeze`（`scenario_gate.py:57`）→
   空集拒绝（`pipeline.py:1989-2010`）→ 重入执行（`pipeline.py:2017`）。
3. **受理校验语义缺口**：`_apply_scenario_freeze` 对盘上集（judge 直改后的）是
   「坏条目**剔除留痕、不整批拒绝**，合法子集照常进入执行」（`scenario_gate.py:63-66`），
   仅全批非法（空集）才 abort。词表违规单条混入时被静默剔除、修复面缩水，
   而 judge 自认为修复成功。
4. **成对撕裂窗口**：`_scenarios_full.json` 备份「仅当产出全部合法时更新，含非法条目
   时保留旧备份」（`scenario_gate.py:67-69`）。judge 直改只触碰 `test_scenarios.json`；
   含非法条目轮备份停留在旧集，后续「无理由缺场景按持久化集回补」把旧定义复活
   （本次事故的端口漂移潜伏 2 轮即此机制）。
5. **词表违规潜伏**：judge 直改落盘的 `run` 步骤入 api 场景等跨 kind 词表违规，
   结构上要到场景执行（验收期）才失败——中间轮次全部白烧。

## 2. 同款门基建已存在（复用对象）

`_exec_revise_scenario_reverify`（`core/dashboard/data/admin_actions.py:2687`，admin
裁决修订通道，`adjudication_choices.py:544` 确认其为「唯一写端」）已内置全部所需纪律：

- **步骤 4** fail-closed 整批预校验：`validate_scenario_dicts(scenarios)` 任一条非法
  即整体拒绝（`admin_actions.py:2819-2824`，错误清单取前 3 条拼 error）；
- **步骤 5b** 成对落盘：`prepare_scenarios_for_write` 盖版本戳后按「先 `_scenarios_full`
  后 `test_scenarios`」固定顺序成对同覆盖（`admin_actions.py:2875-2888`）——对账回填
  以 `test_scenarios.json` 为权威源，后写使中断撕裂对收敛回旧一致态；
- 写前逐文件快照、任一步失败回滚不留半改状态（`admin_actions.py:2826-2852`）。

`validate_scenario_dicts`（`core/verify_engine/scenarios.py:1872`）→ `TestScenario.validate()`
按 kind 走 per-kind 词表（`scenarios.py:1364-1366`，权威源 `KIND_ACTIONS`），跨 kind
词表违规（`run` 入 api 场景）在门覆盖内——**同一门可拦本次事故的直接根因**。

## 3. 设计决策

### D1：受理路径换 fail-closed 整批语义，与 planner 收编语义有意分化

judge 修复受理路径在 `_apply_scenario_freeze` **之前**加「受理预检」：读盘原始 JSON
数组 → `validate_scenario_dicts` → 非空错误清单即拒收本轮修复（不再进入既有
剔除继续/重入流程）。不沿用 planner 产出收编的「剔除继续」语义，理由：

- judge 修复是**修订通道**性质（同 `revise_scenario_reverify`），预算有限
  （`_SCENARIO_REPAIR_MAX_ROUNDS`，模板口径 2 轮），带病采纳=把潜伏问题推迟到
  验收期（本次事故实证形态）；
- 「剔除继续」会静默缩水场景面 + 保留撕裂窗口，judge 却收到修复成功的申报语境。

`_apply_scenario_freeze` 本身的剔除语义**不改**（planner 产出收编路径行为零变化）；
预检通过后才进入它，其空集拒绝分支保留为防御性兜底。

### D2：拒收路由复用既有先例，MUST NOT 返回 False

接线形态照抄预算耗尽拒收分支（`pipeline.py:1955-1976` 先例）：

- `update_spec` error 留痕：文案含「写端校验失败拒收」+ 逐条错误清单前 3 条
  （裁剪口径同 `admin_actions.py:2823`），spec 保持 testing；
- `_record_repair_claim(self, spec_name, rejected=True)` 记账（D3/D4 预算口径字段复用）；
- **返回 True**（比照空集拒绝先例）——调用方平铺尾段依赖「scenario-repaired 已由
  专门分支消费」前提，返回 False 会穿透守卫未重执行即假收敛为 verified
  （`pipeline.py:1941-1945` 已有明文风险注记）；
- 重修机会：拒收轮 judge 裁决产物照常落盘，错误清单经既有重派上下文（prev-error
  注入链）回传下轮 judge；消耗既有预算，**不新增预算、不改 `_SCENARIO_REPAIR_MAX_ROUNDS`**。

### D3：受理采纳成对落盘

预检通过后，受理采纳路径的写回须满足成对语义：`test_scenarios.json` 与
`_scenarios_full.json` 同版本戳成对覆盖、先 `_scenarios_full` 后 `test_scenarios`。
实现时先核对 `_apply_scenario_freeze` 现有备份写点（`scenario_gate.py:325`）在
「预检通过 ⇒ 全批合法」前提下是否已自然满足成对纪律；已满足则本决策退化为
回归测试锚点（锁行为），未满足才改写点。

### D4：judge 协议模板同步

`agents/planner-judge.md` 原地修复协议段（`:144-148`）追加：写回将按
`validate_scenario_dicts` 整批校验、任一条非法（含词表违规）即拒收本轮修复并按
逐条错误清单重修；申报前自校验义务。话术风格对齐 admin 修复约束段
（`core/agent_runner/prompt_builder.py:886-908` `_admin_scenario_fix_constraints`）。
机械门挂受理点（fail-closed），模板约束只是降低失败率的第一道防线——与
`pipeline.py:1938-1940`「prompt 层约束会被模型漂移突破」的既有判断一致。

### D5：兼容边界（零变化清单）

- planner 产出收编路径（`_apply_scenario_freeze` 剔除继续）行为零变化；
- admin `revise_scenario_reverify` 通道零变化（本 SPEC 只**复用**其纪律形态）；
- fast-track Phase 2 写入车道已有独立 schema 门（`prompt_builder.py:807-810`），不接入；
- `_handle_scenario_repaired` 既有分支顺序不变：预算检查 → 耗尽拒收 → **（新）预检
  拒收** → `_apply_scenario_freeze` → 空集拒绝 → 重入。

## 4. Non-Goals

- **语义级错误不拦**：端口/URL 客观错误、断言弱化、选择器失配等非机械可判违规
  不在 `validate_scenario_dicts` 能力内，仍靠验收期执行 + judge 出题同源知识；
  本 SPEC 只承诺在受理瞬间拦「结构必填 / per-kind 词表 / JSON 形态 / 成对撕裂窗口」类可机械判定违规。
- 不改修复预算值与升级路径（`fix-recovery-path-blockers` 的两态处置保持原样）。
- 不动 dashboard 裁决通道与 `SCENARIO_REVISION_*` 白名单体系。

## 5. 风险与缓解

- **拒收循环**：judge 反复产出非法集会空烧预算轮。缓解：预算 2 轮上限 + 耗尽两态
  处置（排程重验 → 升级人工）既有兜底，拒收记账字段（`_record_repair_claim`）提供
  告警取数。
- **预检与收编双重校验的报错口径漂移**：预检 fail-closed 整批、收编剔除继续，
  两语义并存。缓解：预检挂在受理点（judge 修复专属），`_apply_scenario_freeze`
  代码不动，报错文案各自单源。
