# 验证报告：evo-verifier-result-single-source

> ⚠️ 本报告由框架于 2026-09-14T22:51:35Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-14T22:51:35.838160+00:00

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.33M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| entry-read-verdict-single-source | R1 读取单一来源：统一入口 _read_verdict 单测组 8 例全绿——verify-progress/<spec>/ 优先于共享残留（primary 优先）、双文件缺失 fail-closed(missing)、共享 role=implementer 拒绝(foreign-role)、缺 role 旧格式遗留拒绝、role=verifier 合法采信、spec 戳不匹配拒绝(foreign-stamp)、共享非法 JSON 拒绝(parse)、role 通过后 status 白名单外归因(unknown-status)。出处：tests/test_verdict_contamination.py:137 TestReadVerdictEntry（入口实现 core/pm_engine/verification.py:5663） | pass | 0/5 | - |
| read-failclosed-missing-parse | R1 fail-closed 语义（异常路径）：verify-progress 与主树共享两文件全缺失 → _read_verdict 返回 failure("missing") 而非 None 等价放行；主树共享文件为非法 JSON → failure("parse") 拒绝（add-verify-contract-autodraft 裸换行签名）。出处：tests/test_verdict_contamination.py:149（test_missing_both_files_unreadable）、:190（test_shared_invalid_json_parse_failure） | pass | 0/3 | - |
| direct-codepath-verdict-gating | 直接行为级验证（独立于 pytest 夹具，驱动真实 _read_verdict 代码路径）：implementer 残留（role=implementer + run_id 不可解析 -\d{10,}-a\d+$）→ ok=False/reason=foreign-role；缺 role 旧格式遗留 → foreign-role；role=verifier 合法 → 采信 status=bug-found；primary 存在时共享残留被忽略（status=verified）。输出 JSON 供结构断言。出处：core/pm_engine/verification.py:5663（_read_verdict） | pass | 0/7 | - |
| legacy-implementer-residual-redispatch | add-web-ui 误判链红灯复现（回归核心）：legacy 路径读到主树共享 implementer 残留 （role=implementer、run_id 不可解析）→ 不判 blocked，走 stale/foreign 护栏 re-dispatch（status 回 implemented、error 含 replayed、不触发 on_spec_verified/on_spec_bug_found/人工升级）；缺 role 旧格式残留同路径同样 re-dispatch——0 次 blocked 误判。出处：tests/test_verdict_contamination.py:214 TestLegacyContamination（:228 :240） | pass | 0/4 | - |
| legacy-valid-verifier-and-verified-gate | legacy 合法路径不回归：role=verifier 合法裁决照常消费（status=bug-found 触发 _on_spec_bug_found）；已 verified 稳定性快照 + 共享残留 → verified 放行门拒绝 re-dispatch（status 保持 testing、不覆盖 verified、不触发裁决副作用）。出处：tests/test_verdict_contamination.py:248（test_legacy_valid_verifier_still_works）、:256（test_verified_gate_protects_against_redispatch） | pass | 0/3 | - |
| three-stage-contamination-guard | 三阶段（planner/judge）路径污染护栏：primary 存在且合法 → 共享 implementer 残留 被忽略（verified/done 采纳不回归）；primary 缺失 + 共享残留 → 重写 judge 产出 fresh verdict 被采纳（verified/done），残留不干扰裁决、不触发 bug-found。出处：tests/test_verdict_contamination.py:332 TestThreeStageContamination（:335 :347） | pass | 0/4 | - |
| mechanical-anchor-unified-entry | 机械锚点（R3 防零变更洗白）：legacy 与三阶段两处裁决读取 MUST 经统一入口 _read_verdict（patch wraps 断言调用）——测试不预先全绿的空跑防护。出处：tests/test_verdict_contamination.py:382 TestMechanicalAnchors（:385 :400） | pass | 0/3 | - |
| copyback-role-injection-all-agents | R2 写入语义隔离：_execute_agent 拷回 worktree 根 .fenix-run-result.json → 主树共享 .fenix/.fenix-run-result.json 时按 agent_type 注入 role（verifier=verifier / planner-judge=judge / planner-plan=planner / implementer=implementer）与 spec 戳，role 取值=写者全集（implementer\|verifier\|planner\|judge\|repair，fast-track 语义同 implementer）。出处：tests/test_verdict_contamination.py:424 TestCopybackRoleInjection（:478 :486 :513 :544）；注入点 core/agent_runner/runner.py:144（AGENT_TYPE_TO_ROLE）、:2704 | pass | 0/6 | - |
| copyback-invalid-json-raw-bytes | R2 异常路径：worktree 侧结果文件为非法 JSON（裸换行，add-verify-contract-autodraft 事故签名）→ 拷回维持原始字节、不注入 role（读侧按 parse 归因、不破坏字节）。出处：tests/test_verdict_contamination.py:572（test_invalid_json_copyback_keeps_raw_bytes） | pass | 0/2 | - |
| full-contamination-suite-regression | 全量污染回归套件 21 例一次通过（R1 入口 8 + legacy 4 + 三阶段 2 + 机械锚点 2 + 拷回 role 注入 4 + 拷回异常 1），验证本 SPEC 全部改动点无相互回归。出处：tests/test_verdict_contamination.py 全文件（21 例） | pass | 0/2 | - |
| deliverable-anchor-source-check | 交付物源码锚点（确定性证据）：统一入口 def _read_verdict 存在于 core/pm_engine/verification.py；role 映射常量 AGENT_TYPE_TO_ROLE 存在于 core/agent_runner/runner.py；两模块可正常导入无语法/依赖错误。出处：core/pm_engine/verification.py:5663、core/agent_runner/runner.py:144,2704 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 11 个（第 1 轮）。

- 首轮写入 11 个场景

