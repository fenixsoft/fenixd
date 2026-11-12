# Arbiter 处置黑名单与救回机械防线

<!-- knowledge: capability=arbiter-blacklist-disposition rev=1
     sources=spec/changes/add-arbiter-blacklist-disposition -->

Arbiter 车道处置动作面的治理模型与机械防线：禁项外默认可救，禁项枚举、语义保持证明器、救回工具箱与 resolved 证据硬门构成全链可机器校验的处置契约。车道级路由、单飞与配额语义见 [arbiter-lane](arbiter-lane.md)。

## 规则

- **处置模型黑名单制**：判定焦点是「是否命中禁项」而非「是否在许可清单内」，禁项外一律默认可救。五类禁项在单源模块 `core/pm_engine/arbiter_blacklist.py` 枚举，prompt 禁项文案由同一模块导出注入（文案与谓词同源，禁双源漂移）；`arbiter_blacklist.enabled=false` 时硬门整体直通、行为与黑名单机制缺席一致（回滚路径）。
- **五类禁项**：
  - B1 生产账本副作用：对 `admin_alerts.json` 等生产存储的状态变更（标记已处理、裁决消费、批量清理，如执行 `POST /api/alerts/clear`）。
  - B2 人工裁决通道代行：消费/关闭归属人工的裁决物（judge_rerun_cap 裁决包终审、impl_unattainable 确认等）。
  - B3 破坏性动作直执：删除/覆写框架自有产物——场景文件经证明器门的成对写除外。
  - B4 验证契约放宽：断言期望弱化、场景删除、期望向实际看齐的自证。
  - B5 越界写：直写 STATE.md 本体、他 spec 分支文件、主树源码。
- 命中禁项的动作面被黑名单门拒绝，处置降级 escalate 并在台账留痕命中禁项编号。B3/B5 是提示词级红线的机械门收敛——机械门为唯一防线，提示词约束会被模型漂移突破（judge 写回受理门同源教训）。
- **语义保持证明器**（B4 机械判别）：`core/verify_engine/scenario_semantics.py` 的 `prove_scenario_fix` 确定性纯函数，输入修复前后场景集 JSON，逐场景逐断言 diff 三分类（收紧 tighten/放松 relax/中性 neutral），场景删除按 relax 计；存在未获准 relax 断言即净放宽，净放宽即拒。
- relax 断言须附机器可校验正当性码才获准；正当性码白名单闭合（首码 `global-counter-nondeterministic`——共享生产账本聚合量不可静态锚定，锚验证场景环境耦合红线），未知码拒绝。regex 收窄、选择器作用域化、等待调整、文案注记判中性。
- **B1 合规化 carve-out**：拆除禁项违规步骤（位置点击生产入口、破坏性批量确认路径）并以机械形态断言替换、无新增生产端点的改写判中性，不因断言集变化计放宽。
- **场景修复落盘契约**：与 judge 写回受理门同契约——成对覆盖 `_scenarios_full.json` 与 `test_scenarios.json`、同契约版本戳、先备份后主文件、撕裂对收敛回旧一致态。
- **救回工具箱**：T1 黑名单域内场景鲁棒性修复（机械修复类白名单：选择器向 fixture/种子标记作用域化、expect_network 守卫收紧、等待时序加固、破坏性场景转安全变体）；T2 稳态复跑探针（对失败面在稳态 checkout/实例上只读复跑，MUST NOT 变更任何账本状态，结果落 `probe_transient` 证据类）。工具产出才是救回证据，非工具的处置主张不构成有效证据类。
- T2 探针在稳态复现同一失败时 MUST NOT 申报 resolved——产出裁决包并附探针产物证据升级人工。
- **resolved 硬门**：处置副作用接线（`_apply_disposition_side_effects` 入口前置）按黑名单扫描→证明器→证据类校验三级顺序执行；`outcome=resolved` MUST 携带至少一类有效救回证据（`scenario_fix` 过证明器 | `probe_transient` 探针结果 | 既有 `artifact_rescue`/`counter_reset`/`cleanup` 形态），否则框架自动降级 escalate——报告原样转裁决包、spec 状态与计数不动、台账留痕降级与命中原因。黑名单命中与证明器拒绝同走本降级路径；即使携带有效证据，禁项命中仍降级。
- **降级不折算 run 失败**：硬门拒绝导致的降级是处置结论而非执行故障，arbiter run 记合法终态，不触发同签名失败重试计数、不烧配额。

## 代码锚点

- 主实现：`core/pm_engine/arbiter_blacklist.py`（B1–B5 禁项枚举与谓词、prompt 禁项文案渲染单源、enabled 开关）
- 单源符号：`core/verify_engine/scenario_semantics.py`（`prove_scenario_fix` 确定性证明器与正当性码白名单）
- 消费方：`core/pm_engine/arbiter.py`（处置副作用入口三级硬门接线）；`agents/arbiter.md`（禁项文案同源注入）；`core/pm_engine/verification/escalation.py`（早期触发信号发射的黑名单门控）
- 守卫测试：`tests/test_arbiter_blacklist.py`、`tests/test_scenario_semantics.py`

## 溯源

- 2026-11-12 add-arbiter-blacklist-disposition（spec/changes/add-arbiter-blacklist-disposition/） — 新建本页：处置哲学由「白名单+判定反例」反转为黑名单制（用户裁定），B1–B5 禁项单源与机械门、语义保持证明器与正当性码白名单、B1 合规化 carve-out、救回工具箱 T1/T2、resolved 证据硬门与自动降级、enabled=false 直通回滚路径
