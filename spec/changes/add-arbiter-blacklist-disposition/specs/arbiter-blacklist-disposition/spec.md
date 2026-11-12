# arbiter-blacklist-disposition Specification

## ADDED Requirements

### Requirement: B1–B5 禁项单源配置

系统 SHALL 提供黑名单禁项单源模块（`core/pm_engine/arbiter_blacklist.py`）：枚举五类禁项与机器可判定谓词——B1 生产账本副作用（对 admin_alerts.json 等生产存储的状态变更：标记已处理、裁决消费、批量清理）；B2 人工裁决通道代行（消费/关闭 judge_rerun_cap 裁决包、impl_unattainable 确认等归属人工的裁决物）；B3 破坏性动作直执（删除/覆写框架自有产物——场景文件经证明器门的成对写除外）；B4 验证契约放宽（断言期望弱化、场景删除、期望向实际看齐的自证）；B5 越界写（直写 STATE.md、他 spec 分支、主树源码）。prompt 构建与机械门 SHALL 消费同一单源（禁项文案注入 arbiter prompt 与谓词实现同源），禁项外一律默认可救。B3/B5 将既有提示词级红线收敛为门可校验谓词（提示词约束会被模型漂移突破，机械门为唯一防线——judge 写回受理门同源教训）。

#### Scenario: 禁项外默认放行

- **WHEN** Arbiter 报告申报黑名单域内救回（如选择器作用域化、网络守卫收紧、稳态复跑探针）
- **THEN** 黑名单门不拒绝，处置按 resolved 硬门流程继续

#### Scenario: B1 生产副作用拦截

- **WHEN** 救回方案包含对生产账本的状态变更（如执行 POST /api/alerts/clear、改写 admin_alerts.json 告警状态）
- **THEN** 黑名单门拒绝该动作面，处置降级 escalate 并留痕命中禁项编号

#### Scenario: B2 裁决代行拦截

- **WHEN** 救回方案会消费或关闭人工裁决包（judge_rerun_cap 裁决包、impl_unattainable 确认）
- **THEN** 黑名单门拒绝，仅产裁决包交人工

#### Scenario: B4 契约放宽拦截

- **WHEN** 场景修复被证明器判为净放宽且无正当性码
- **THEN** 黑名单门拒绝，处置降级 escalate

#### Scenario: B5 越界写拦截

- **WHEN** 救回方案写 STATE.md 本体、他 spec 分支文件或主树源码
- **THEN** 黑名单门拒绝，处置降级 escalate

### Requirement: 语义保持证明器

系统 SHALL 提供确定性证明器（`core/verify_engine/scenario_semantics.py`）：输入修复前后场景集 JSON，对逐场景逐断言 diff 输出三分类（收紧 tighten/放松 relax/中性 neutral），场景删除按放松计；整体净放宽（存在 relax 断言且无获准正当性）即拒绝。获准正当性 SHALL 为机器可校验正当性码白名单（如 `global-counter-nondeterministic`——共享生产账本聚合量不可静态锚定，锚定知识源 `spec/knowledge/domains/verify-pipeline/scenario-env-coupling.md`），relax 断言 MUST 附码才可获准。B1 合规化 carve-out：拆除黑名单违规步骤（位置点击生产入口、破坏性批量确认路径）并以机械形态断言替换的改写，SHALL 判中性不计放宽。场景修复采纳落盘 SHALL 与 judge 写回受理门同契约：成对覆盖 `_scenarios_full.json` 与 `test_scenarios.json`、同契约版本戳、先备份后主文件、撕裂对收敛回旧一致态。

#### Scenario: 选择器作用域化放行

- **WHEN** 改状态 click 由位置选择器（`button:has-text("标记已处理")` + `.first` 首行）改为种子行作用域（`.ant-list-item:has-text('[provfix-seed] …') button:has-text(…)`）且 expect_network 路径同步收紧
- **THEN** 证明器分类为收紧/中性，净判定通过，修复获准

#### Scenario: 聚合量绝对值改形态断言带码放行

- **WHEN** 徽标断言由 exact `3` 改为 regex `\d+` 且附正当性码 `global-counter-nondeterministic`
- **THEN** 证明器计该 relax 为获准，净判定通过

#### Scenario: 无码放宽拒绝

- **WHEN** 断言期望由具体值放宽为宽泛匹配且未附正当性码
- **THEN** 证明器输出 relax（未获准），净判定拒绝，处置降级 escalate

#### Scenario: B1 合规化改写 carve-out

- **WHEN** 场景原含破坏性批量确认路径执行，修复后改为开窗断言机械形态+取消路径 noop 并移除确认点击
- **THEN** 证明器按合规化改写判中性，不因断言集变化计放宽

### Requirement: 救回工具箱

Arbiter 车道 SHALL 配备两类救回工具并以证据落报告：T1 黑名单域内场景鲁棒性修复（机械修复类白名单：选择器向 fixture/种子标记作用域化、expect_network 守卫收紧、等待时序加固、破坏性场景转安全变体）；T2 稳态复跑探针（对失败面在稳态 checkout/实例上只读复跑，MUST NOT 变更任何账本状态，结果落 `probe_transient` 证据类）。工具产出为救回证据，非工具的处置主张不构成有效证据类。

#### Scenario: T1 场景修复救回

- **WHEN** 同签名失败为位置点击串扰类且修复在 T1 机械修复类白名单内
- **THEN** Arbiter 应用修复、证明器过门、resolved 附 scenario_fix 证据，spec 恢复流转

#### Scenario: T2 探针破两源互证

- **WHEN** judge 归因与官方验证结论冲突（如 dependency_skipped 伪失败 vs 官方 fail）、既有两源互证前提不可满足
- **THEN** Arbiter 以 T2 探针在稳态复跑，通过即得 probe_transient 证据，可申报 resolved

#### Scenario: T2 探针复现失败不硬解

- **WHEN** T2 探针在稳态复现同一失败
- **THEN** Arbiter MUST NOT 申报 resolved，产出裁决包并附探针产物证据升级人工

### Requirement: resolved 硬门与自动降级

框架侧处置副作用接线（`core/pm_engine/arbiter.py` `_apply_disposition_side_effects`）SHALL 对 `outcome=resolved` 执行硬门：报告 MUST 携带至少一类有效救回证据（scenario_fix 过证明器 | probe_transient 探针结果 | 既有坏产物拯救/计数复位/无主产物清理形态），否则自动降级为 escalate——报告原样转裁决包、spec 状态与计数不动、台账留痕降级与命中原因。黑名单门命中与证明器拒绝同走本降级路径。MUST NOT 因硬门失败折算 arbiter run 失败（run 本身合法完成，降级是处置结论而非执行故障）。

#### Scenario: 有效证据放行

- **WHEN** resolved 报告携带过门 scenario_fix 证据
- **THEN** 硬门通过，既有副作用接线执行（显式 status 解冻+计数清零），原告警终态化

#### Scenario: 无证据自动降级

- **WHEN** resolved 报告无任何有效救回证据类
- **THEN** 框架自动降级 escalate：裁决包落人工队列，spec 状态不变，台账记录降级原因

#### Scenario: 降级不折算 run 失败

- **WHEN** 硬门拒绝导致降级
- **THEN** arbiter run 记合法终态（非 run-failed），不触发同签名失败重试计数
