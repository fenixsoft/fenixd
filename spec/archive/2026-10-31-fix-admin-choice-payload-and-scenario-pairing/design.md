# Design: fix-admin-choice-payload-and-scenario-pairing

## Context

裁决执行器 `execute_adjudication_choice`（core/dashboard/data/admin_actions.py:4179）的 `note` 参数是载荷唯一入口：人工路径由 alert-resolve 端点从请求体传入（可用），Administrator 自动路径由 `admin_monitor._apply_choice_execution` 以 `actions_taken` 截断 200 字的依据文本充当（core/admin_monitor.py:7512）。`revise_scenario_reverify` 执行器（同文件 :2608 起）强制要求 `note` 为 JSON 载荷（`{"scenarios": [...], "reason": "...", "fixture_files": [...]}`，实测约 47KB），故自动路径选该选项必失败（实证 ERROR 2026-10-27T17:55:40）。处置记录本身是 JSON 文件（`admin_disposition-<run_id>.json`）， Administrator 完全有能力写入结构化载荷——缺的只是字段契约与透传链。事故中 Administrator 还绕开执行器直接手改 `test_scenarios.json` 未成对更新 `_scenarios_full.json`，暴露 prompt 契约对「修订必走载荷路径」无约束。

## Goals / Non-Goals

**Goals**
- Administrator 自动处置可携带动作载荷直达执行器，`revise_scenario_reverify` 自动执行从「结构性必败」变为可用。
- 载荷要求收敛注册表单源；缺载荷 fail-closed，不产生假收口。
- prompt 契约固化「修订必走载荷路径、禁止 out-of-band 手改场景/夹具文件」。

**Non-Goals**
- 不改 alert-resolve 人工端点与执行器载荷契约本身。
- 不对 `choice_payload` 做内容级预校验（第二道门）——非法载荷由执行器既有解析失败路径拒绝，告警保持未处理即可。
- 不改变处置失败后 escalation 信号的重派/重试节奏（沿用既有 admin 车道失败语义）。

## Decisions

1. **载荷走处置记录字段，不开旁路文件。** 处置记录（`admin_disposition-<run_id>.json`）已是原子交接产物（读取即删、内容落 final），新增 `choice_payload` 字符串键零新机制。备选「载荷写独立文件、处置记录存路径」被否： reintroduces「文件信号无消费者/残留清扫」事故族（fenixd 既有教训），且 final 记录载荷在场即审计闭环。
2. **`requires_payload` 收敛注册表单源。** `adjudication_choices.py` 条目加静态布尔键（初始仅 `revise_scenario_reverify: true`），`resolve_choice` 结果原样携带；消费侧（硬门、`_apply_choice_execution`）只读注册表，不维护本地选项名单——对齐 fix-global-signal-choice-execution 1.1 的「解析收敛单源」先例。备选「消费侧硬编码集合」被否：新增载荷型选项时双处漏改即复发。
3. **硬门放处置收口处，与既有两道门同型。** maintenance_runs.py 既有「admin 未写处置文件」「result 非法」两道 fail-closed 门（:443-489）之后追加第三道：`success` 且 `choice_id` 经注册表解析（`signal_type` 取自本次 admin 信号上下文）为 `requires_payload` 且 `choice_payload` 缺空 → 折算失败并点名缺口。这样「resolved 但执行必败」的假收口在落 final 前就被拦下，escalation 信号按既有失败语义保持未处理。
4. **`_apply_choice_execution` 双层设防 + note 载荷优先。** 该函数本就先 `resolve_choice` 做作用域守卫——顺带判 `requires_payload`：载荷空且必需 → 返回 not-ok skipped（信号保留待重审，与全局信号跳过同型），不再空打执行器制造必然失败日志；载荷非空 → `note=choice_payload` 整体直传（不截断）；非必需选项维持 `note=actions_taken[:200]` 现状。硬门（决策 3）与执行前置（本条）互为冗余防线，任一生效即阻止假收口。
5. **prompt 契约增补落在既有「裁决选项消费契约」段内**（agents/administrator.md :114 起）：新增一条规则（修订场景/夹具 MUST 经 `choice_payload`+`revise_scenario_reverify`，MUST NOT 直接编辑 `test_scenarios.json`/`_scenarios_full.json`/夹具文件，附成对一致与对账回填理由），处置记录模板（:159 起）补 `choice_payload` 可选键说明。不新增独立段落，控制 prompt 体积。

## Risks / Trade-offs

- [LLM 写出的 `choice_payload` JSON 非法] → 执行器既有载荷解析失败路径拒绝，告警保持未处理可重试；硬门只查在场不查内容（spec 明示不设第二道门），失败形态与人工传错载荷一致，无新增爆炸半径。
- [final 记录与 DISPOSITION 留痕体积增大约 50KB/次] → AdminStore.append 实测承载 47KB 无碍（本日人工裁决同体量留痕已落盘）；归档保留策略沿用既有，不单独治理。
- [存量处置记录无 `choice_payload` 键] → 全部读取点 `.get` 缺省空串，行为与变更前逐字节一致，零迁移。
- [prompt 再增一段加剧 administrator 契约膨胀] → 增补压缩为一条规则 + 模板一键，不复述执行器内部步骤。

## Migration Plan

纯增量变更，无数据迁移：部署后新处置按新契约运行，存量记录按缺省值走旧路径。回滚 = revert 提交，无状态残留（新键仅存在于运行时 JSON，读侧缺省兼容）。

## Open Questions

（无——载荷契约形态、单源归属、门位均已由本设计钉死。）
