# 验证报告：evo-add-judge-incremental-attribution

> ⚠️ 本报告由框架于 2026-09-13T06:52:31Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 6/6 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 6/6 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.28M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| judge-attr-incremental-save-roundtrip | CLI：judge 归因逐场景增量写盘——save_attribution 写入 23 个场景条目后 load_attribution 读回，结构含 format_version + scenarios 列表且条目数一致（SPEC 场景「单轮多场景增量落盘」；交付物 core/verify_engine/judge_files.py:143 save_attribution / :54 load_attribution） | pass | 0/2 | - |
| judge-attr-legacy-compat-read | CLI：旧整块结构向后兼容读——load_attribution 读入旧版单块归因产物不报错，自动迁移为 migrated_from_legacy=True 且 scenarios 数组仅含 legacy_0 单条目（SPEC 场景「旧结构兼容读」；交付物 core/verify_engine/judge_files.py:97 _migrate_legacy_attribution / :330 migrate_legacy_attribution_file） | pass | 0/2 | - |
| judge-attr-mark-status-single | CLI：归因条目可独立覆写——mark_scenario_status 将场景 s3 标记为 requeue，其余 4 条 accept 保持不变，get_requeue_scenarios 仅返回 s3（SPEC 场景「各自可独立读取与覆写」；交付物 core/verify_engine/judge_files.py:186 mark_scenario_status / :219 get_requeue_scenarios） | pass | 0/2 | - |
| judge-attr-partial-requeue-keeps-accepted | CLI：查重拒绝场景级回炉——运行 pytest TestPartialRequeueKeepsAccepted 验证：3 个重复场景 requeue、2 个差异化场景 accept 保留复用；回炉清单 requeue_manifest.json 仅含重复子集（SPEC 场景「部分场景重复仅回炉子集」；交付物 tests/test_judge_incremental_attribution.py TestPartialRequeueKeepsAccepted） | pass | 0/2 | - |
| judge-attr-full-requeue-escalation | CLI：全量重复仍全量回炉+告警——运行 pytest TestFullRequeueEscalates 验证：全部场景 requeue 触发 escalation 告警，spec 状态进入 blocked（SPEC 场景「全量重复仍全量回炉」；交付物 tests/test_judge_incremental_attribution.py TestFullRequeueEscalates） | pass | 0/2 | - |
| judge-attr-manifest-prompt-injection | CLI：回炉清单 prompt 注入——运行 pytest TestRequeueManifestPromptInjection 验证：manifest 存在时注入回炉子集+accept 保留纪律；缺失/损坏时静默降级；planner-judge.md 模板含增量落盘契约（SPEC 场景「回炉驱动」2.2；交付物 tests/test_judge_incremental_attribution.py TestRequeueManifestPromptInjection） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 6 个（第 1 轮）。

- 首轮写入 6 个场景

