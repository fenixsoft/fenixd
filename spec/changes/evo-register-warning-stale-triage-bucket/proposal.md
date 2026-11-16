# warning_stale_triage 信号裁决桶注册

## Why

`warning_stale_triage` 由验证管线在「同一 spec 场景连续 ≥2 轮 warning」时发出（core/pm_engine/verification/escalation.py:1190），但裁决注册表的 13 个桶（ADJUDICATION_CHOICES，adjudication_choices.py:465 = 桶 0 三信号 + _ADJUDICATION_REGISTRY:237 十桶）不含它。后果是结构性的：链上白名单为空（choices_for_admin_chain 对未注册信号返回空元组），任何 Admin 产出都会被判「choice 越界（人类拍板面专属）」并转单 Arbiter；人工 alert-resolve 也因空 choice 集直接 400。2026-11-12 一条信号因此产生 1 次 admin run + 2 次 Arbiter run（3318.3s / $9.33844，其中 $4.717862 为缺桶直接增量），且信号最终仍 handled=false。该信号 2026-09-23、2026-10-26（两次）、2026-11-12 共复发 4 次。

## What Changes

- `core/dashboard/data/adjudication_choices.py`：新增模块常量 `_ACK_TRIAGE`（id=ack_triage、action=ack_self_heal、spec_scoped=true、risk_tier=reversible-experiment，复用既有 ack 执行分支）；注册新桶 `warning_stale_triage: (_ACK_TRIAGE, _REVISE_SCENARIO_REVERIFY)`——后者按引用复用单源常量，requires_payload=true 语义不变。
- `core/pm_engine/escalation_chain.py`：`_admin_choice_allowlist` 区分「信号未注册（空集）」与「已注册但选项被全部过滤」两种空集，越界转单文案对前者改为「信号未注册裁决桶: <choice_id>」；拒绝语义不变（不因归因修正而放行）。
- `tests/test_adjudication_choices.py`：注册表覆盖清单 13 → 14，补 `warning_stale_triage` 选项集断言。
- 新增 `tests/test_warning_stale_triage_bucket.py`：覆盖注册生效、告警携带 choices、链上白名单、载荷门与未注册信号回退不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `adjudication-choices-registry`: 新增 `warning_stale_triage` 桶（`ack_triage` + `revise_scenario_reverify`），使分诊类升级信号具备可留痕的结构化处置出口；越界归因区分「未注册信号」与「人类拍板面专属」。

## Impact

- 代码：`core/dashboard/data/adjudication_choices.py`、`core/pm_engine/escalation_chain.py` 两个文件；测试两个文件。
- 行为：新发出的 warning_stale_triage 告警自动携带 choices（choices_for 泛化生效），链上 Admin 可在 `ack_triage` 与 `revise_scenario_reverify` 之间选择；存量告警记录不做批量改写——本信号存量记录因发射时注册表为空而未写 choices 键，alert-resolve 校验对键缺失记录本就回退读注册表（alert_routes.py 既有回退逻辑），注册后存量告警在人工裁决面即时获得新选项，无需重发。
- 非目标：不改 triage 信号的发射频率与 `triage_recheck.json` 去重；不把该信号加入自动闭环条件（alert_lifecycle 零改动）；不追加 grant_env_exemption / abandon 等人类专属项（若需人类拍板仍走链终点升级）。
