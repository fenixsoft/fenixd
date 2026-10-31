# Proposal: fix-admin-choice-payload-and-scenario-pairing

## Why

2026-10-28 `add-merged-branch-gc` 停车 7.5 小时事故暴露结构性缺口：Administrator 车道查明验证失败真因（场景定义缺陷）并在处置记录填 `choice_id=revise_scenario_reverify` 交框架自动执行，但 `admin_monitor._apply_choice_execution` 只能把 200 字截断的 `actions_taken` 文本当 `note` 传入执行器（core/admin_monitor.py:7512），而 `revise_scenario_reverify` 执行器契约强制要求 JSON 载荷（完整场景集 + fixture，约 47KB）——自动路径结构性不可能满足载荷契约，执行必失败（fenixd.log ERROR 2026-10-27T17:55:40），信号不闭环、escalation 告警滞留未处理、SPEC 以 implemented 态停车等人工。事故中 Administrator 还曾为绕开载荷缺失 **out-of-band 手改 `test_scenarios.json` 而未成对更新 `_scenarios_full.json`**，违反执行器的成对写回纪律，留下旧定义经「无理由缺场景补齐」分支回填复辟的隐患。载荷通道缺失与配对纪律缺约束是两个共因，须一并根治。

## What Changes

- Administrator 处置记录新增结构化 `choice_payload` 字段：JSON 直传通道，不经 `actions_taken` 文本与 200 字截断；沿 AdminDisposition → `_apply_choice_execution` → `execute_adjudication_choice(note=…)` 全链透传。
- choices 注册表选项支持 `requires_payload` 声明（数据驱动；当前仅 `revise_scenario_reverify` 置位），载荷要求收敛注册表单源，不硬编码在消费侧。
- 处置产物硬门扩展（对齐既有「admin 未写处置文件 / result 非法」fail-closed 先例）：`choice_id` 指向 `requires_payload` 选项而处置记录缺 `choice_payload` → 判失败并点名缺口，消灭「resolved 但执行必失败」的假收口。
- `_apply_choice_execution` 的 `note` 来源改为：`choice_payload` 非空传载荷；无载荷且选项非 payload 必需时维持现状传依据文本（`actions_taken[:200]`）。
- `agents/administrator.md` 契约增补：场景定义/夹具修订 MUST 经 `choice_payload` 载荷路径由执行器白名单成对写回（`test_scenarios.json` + `_scenarios_full.json`），MUST NOT out-of-band 直接手改场景定义与夹具供给层文件。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `admin-choices-contract`: 处置记录契约新增 `choice_payload` 结构化载荷键与缺载荷 fail-closed 硬门；自动执行路径 `note` 来源改为载荷优先；prompt 契约增补「场景修订必走载荷路径、禁止 out-of-band 手改」纪律。
- `adjudication-choices-registry`: 注册表选项新增可选 `requires_payload` 声明，消费侧（处置硬门与 `_apply_choice_execution`）按注册表判定载荷要求。

## Impact

- `core/agent_runner/result_gate.py`：AdminDisposition 增加 `choice_payload` 字段（dataclass + to_dict）。
- `core/agent_runner/maintenance_runs.py`：处置记录读取透传 `choice_payload`；产物硬门新增缺载荷判失败分支。
- `core/admin_monitor.py`：`_apply_choice_execution` 的 `note` 来源改为载荷优先。
- `core/dashboard/data/adjudication_choices.py`：注册表条目 `requires_payload` 声明 + 解析助手（`resolve_choice` 结果携带）。
- `agents/administrator.md`：「裁决选项消费契约」段增补载荷纪律与处置记录模板键。
- 测试：`tests/test_adjudication_choices.py`（requires_payload 解析）、处置硬门与 `_apply_choice_execution` 通道测试（既有 admin 处置链测试族扩展）。
- 不改变人工 alert-resolve 端点行为（其 note 通道已可用）；不改变 `revise_scenario_reverify` 执行器载荷契约本身。
