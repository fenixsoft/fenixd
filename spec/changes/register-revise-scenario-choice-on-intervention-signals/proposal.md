# manual-intervention/verify_env_blocked 信号桶注册 revise_scenario_reverify 裁决选项

## Why

结构性缺口已两次实弹发作（2026-10-30 evo-refine-midflight-outlier-dims、2026-11-03 add-knowledge-inbox-pipeline）：revise_scenario_reverify 仅注册于 inconclusive_loop 桶，而 Administrator 对场景争议类升级告警的消费信号是 manual-intervention/verify_env_blocked，resolve_choice 的 scoped-no-reverse 守卫（有意防御，不应拆除）导致「载荷完美也必被拒」，每次都烧满整个 admin run（本次 605s/$1.79）再冻结转人工。fix-admin-choice-payload-and-scenario-pairing 已修载荷通道（requires_payload 落地），本提案补同一缺口族的注册矩阵余量：把该 choice 以 requires_payload=True 形态注册进场景争议会流经的信号桶，让 admin 自动处置通道真正可达场景修订出口。

机制断言已经评审代码证实（2026-11-03）：注册表 11 桶不含 manual-intervention/verify_env_blocked（core/dashboard/data/adjudication_choices.py，revise_scenario_reverify 仅在 inconclusive_loop 桶 224-256 行）；resolve_choice 对未注册 signal_type × spec_scoped 动作返回 scoped-no-reverse（同文件 605-641 行）；执行器同序拒绝（core/dashboard/data/admin_actions.py:3058-3065）。

## What Changes

- 在裁决选项注册表（`core/dashboard/data/adjudication_choices.py`）新增 `manual-intervention` 与 `verify_env_blocked` 两个信号桶，各含既有选项 `revise_scenario_reverify`（requires_payload=True 形态不变；按「跨信号逐字共享的选项提为模块级单源」约定提取为模块常量，三桶按引用复用）。
- `inconclusive_loop` 桶的该选项就地声明改为引用同一模块常量，字段逐字不变；跨桶一致性由 import 期 `_assert_registry_consistency` 自检钉死。
- 消费侧零改动：resolve_choice 桶内精确解析、执行器按 action 分派、requires_payload 载荷门（处置产物硬门 / 自动执行通道）、告警选项自动附加（choices_for）与前端下拉渲染均为 signal_type 泛化实现，新桶注册后自动生效。

## Capabilities

### New Capabilities

（无——本变更全部落在既有能力域）

### Modified Capabilities

- `adjudication-choices-registry`: 信号桶覆盖面扩展——场景争议类升级信号（manual-intervention / verify_env_blocked）获得裁决选项集，场景修订重验出口经 admin 自动处置通道可达。

## Impact

- 代码：仅 `core/dashboard/data/adjudication_choices.py`（模块常量提取 + 两新桶 + inconclusive_loop 引用化）。
- 测试：`tests/test_adjudication_choices.py` 扩展新桶解析断言；相邻契约测试（载荷契约 / 全局信号守卫 / 场景修订出口）零改动预期全绿。
- 行为：manual-intervention / verify_env_blocked 新发射告警自动携带 choices；Administrator 自动处置通道经 resolve_choice 实时解析，注册后立即可达场景修订出口（不受存量告警快照限制）；前端人工下拉对存量告警维持发稿时 choices 快照集，不做回溯。
- 非目标：不拆 scoped-no-reverse 守卫；不动载荷通道；不为两信号追加 grant_env_exemption 等其他选项（无实弹证据支撑，两次事故均为 revise_scenario_reverify，留待同族后续提案按证据成文）。

---

- 立项来源：Arbiter 调查（run_id=None，signature=add-knowledge-inbox-pipeline::verify_env_blocked，source=startup）
- 立项时间：2026-11-03T11:31:05.706642+00:00
- 评审成文：2026-11-03 spec review 就地修补（原 arbiter 最小成文的 What Changes / Capabilities / Impact 占位段补全；design.md / tasks.md / specs/ 首次成文）
