## Context

出题收集：core/code_review.py collect_manifest :856-922（full 档 git ls-files -z 全仓+_is_source_file :806-828 过滤，_SOURCE_EXTS :761-768 含 .py）；排除表 _EXCLUDED_TOP_DIRS :773-784（spec/docs/dist/.fenix/.git/tests）与 _EXCLUDED_DIRS :789-795，均无 thirdparty/vendor；window 档共用消费点 core/admin_monitor.py:1560-1571。提示词：agents/code-review.md:20「其中的路径是产品代码」、:56-58 fenix-ignore 复核规则（只挡同位重报）；fenix-ignore 为文件内注释 [fenix-ignore:<id>]，框架无解析器。台账语义：core/code_review.py:502-603 upsert_findings 同 fingerprint 重报只刷新、新 fingerprint 照建；core/code_fix.py:1694 mark_ignored（IGNORE_ELIGIBLE_SKIP_REASONS :99）。实证：potplayer-base whirehair.py 5 轮 17 item、两轮 fix batch $2.3762/$2.0336、第五轮 LLM 明知 vendored 仍上报（out-code-review-1791306277.jsonl description 原文）。测试先例：tests/test_code_review.py:1138 test_excludes_tests、:1146 test_excludes_generated_artifacts。

## Goals / Non-Goals

- Goals：vendored 缺陷面退出逐轮全价重审；提示词不再把 vendored 宣称为产品代码；排除表单点修改两档自动生效。
- Non-Goals：不做路径排除配置化；不做标注驱动的 diff 面过滤；不动台账/指纹语义；不界定上游同步窗口流程。

## Decisions

- D1 硬排除优于自动预标 not_worth_fixing：排除在收集层生效零 token 成本；预标仍要先出题评审才能发现 vendored 属性（每轮评审成本照付）。vendored 目录名是稳定信号，取 thirdparty/third_party/vendor 三段精确匹配；external 歧义大（仓内自有代码可能叫 external）不收。
- D2 提示词第二道防线保留并补强 :56-58 fenix-ignore 复核规则：排除表可能被非标准 vendored 布局绕过，带上游同步标注的文件按规则不出题，兜底零漏审风险——标注是既有结案产物，无新增约定。
- D3 排除表沿 tests/ 排除先例（:779-783，2026-09-19 用户决策）硬编码、不做配置面：单点两行改动，配置化留待出现真实项目差异需求。

## Risks / Trade-offs

- vendored 目录内若有个别文件实际参与产品构建、需要审查：极端罕见（本案 996 个受控第三方文件中仅 1 个 .py 入面）；确需审查时在上游同步窗口人工触发专项评审，不走 scheduled 全价面。
- 排除后 vendored 缺陷永久静默：fenix-ignore 标注与上游同步注释仍在文件内，风险由上游同步流程承接（正是标注的设计语义）。