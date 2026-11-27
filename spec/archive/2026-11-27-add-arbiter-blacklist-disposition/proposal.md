# Proposal: add-arbiter-blacklist-disposition

## Why

Arbiter 车道现行为「白名单 + 判定反例」：处置哲学是"宁可升级人工"。近 3 天台账（`.fenix/arbiter_ledger.jsonl`）显示升级人工的 2 个案例（consolidate-alerts-to-ops-page、redesign-chain-panel-ui）人工都能救回——所需动作全部是机械可判定的场景鲁棒性修复与稳态复跑验证，却在白名单外交由人工烧掉数十分钟到数小时；consolidate 案例中「改断言」被写成 MUST escalate 反例，而人工改 5 个断言后解冻即全绿（18/18、spec pushed），证明该反例方向性错误。同时今日事故实锤一类新型风险：E2E 机器人可对生产账本产生真实副作用（误处置真实告警、险些批量清剿 12 条生产告警），场景编写期没有任何静态防线拦截。

用户已裁定处置哲学应反转为黑名单机制（"只有特定场景禁止处理，其他都应当能够救回 SPEC"），本 spec 将该裁定落地为机制。

## What Changes

- **Arbiter 处置黑名单化**（哲学反转）：以「默认可救 + 枚举禁项」替换「白名单 + 判定反例」。禁项 B1–B5 单源配置（生产副作用 / 人工裁决通道代行 / 破坏性动作直执 / 契约放宽 / 越界写），禁项外一律默认可救。
- **语义保持证明器（B4 机械判别）**：场景修复前后断言集 diff 逐条分类（收紧/放松/中性），整体净放宽即拒；B1 合规化 carve-out（拆除禁项违规步骤的改写不算放宽）。
- **救回工具箱**：T1 黑名单域内场景鲁棒性修复（选择器作用域化、网络守卫收紧、破坏性场景转安全变体）；T2 稳态复跑探针（第三证据源，破「两源互证」死锁，add-platform-abstraction-layer 先例工具化）。
- **resolved 硬门**：`outcome=resolved` 必须携带有效救回证据类（scenario_fix 过证明器 | probe_transient 探针结果 | 既有①③④ 形态），无证据类自动降级 escalate；场景文件写经证明器门获准（红线 2 修订），成对落盘契约与 judge 写回受理门对齐。
- **介入时机前移 + 防抖**：同签名验证失败 ≥2 轮即早期路由 arbiter（携带新工具箱），不等配额烧穿冻结；同签名救回失败后签名必须变化才可再试；配额沿用 escalation-chain `arbiter_rulings`。
- **场景生产副作用静态规则族**：scenario_static_check 新增 R1（改状态 click×位置选择器交叉，high）/ R2（网络守卫过宽，medium）/ R3（批量破坏端点确认路径执行，critical）/ R4（全局聚合量绝对值断言，medium）/ R5（`<tag>:text-matches` 组件按钮锚定，medium）+ 事故形态 fixtures + 存量回扫 CLI 入口。

## Capabilities

### New Capabilities

- `arbiter-blacklist-disposition`: B1–B5 禁项单源配置与判定、语义保持证明器、救回工具箱（场景修复 + 稳态复跑探针）、resolved 救回证据硬门——黑名单处置模型的核心机制与数据契约。

### Modified Capabilities

- `arbiter-lane`: 处置哲学由白名单+判定反例反转为黑名单；`agents/arbiter.md` prompt 契约重写（默认可救+枚举禁项，判定反例段反转）；报告契约扩展 `rescue_evidence`/`scenario_fixes` 字段；红线 2 修订（场景文件写经证明器门获准）；`_apply_disposition_side_effects` 接入 resolved 硬门与自动降级。
- `escalation-chain`: 加性早期触发（同签名验证失败 ≥2 轮路由 arbiter，冻结路径行为零变化）+ 救回防抖（救回失败后签名变化才可再试）；配额与复位窗语义不变。
- `scenario-static-defect-scan`: 新增生产副作用规则族 R1–R5 与对应 fixtures；新增存量场景集回扫 CLI 入口；既有 4 规则与 fail-open 语义零变化。

## Impact

- 代码：`core/pm_engine/arbiter.py`（处置副作用/降级接线）、`core/pm_engine/arbiter_blacklist.py`（新）、`core/verify_engine/scenario_semantics.py`（新，证明器）、`core/verify_engine/scenario_static_check.py`（规则族）、`core/pm_engine/escalation_chain.py` 与 `core/pm_engine/verification/escalation.py`（早期触发/防抖）、`core/agent_runner/maintenance_runs.py`（run_arbiter 契约）、`agents/arbiter.md`（prompt 重写）、`tests/`（守卫测试扩充）。
- 兼容性：冻结路径与既有升级链行为零变化（早期触发加性）；judge 写回受理门、预算口径、ADR-318 分化行为零变化；知识页 `scenario-env-coupling.md` 为场景红线真相源，规则族实现其机械子集。
- 风险面：证明器误判可能放行弱化修复（以保守分类+净放宽即拒缓解）；早期触发可能增加 arbiter run 量（以同签名 ≥2 阈值+配额+防抖约束）。
