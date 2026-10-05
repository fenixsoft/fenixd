# design — add-codefix-test-targets-fallback-sanitization

## 消毒缺省值选型

替换为 tests/ 而非剥离参数：剥离对 str 形态留双空格、对 list 内嵌形态（dir={test_targets}）产生 dir= 畸变、且 pytest「无收集目标」走 rootdir 收集语义不可控；tests/ 与 _is_test_path 前缀识别、verify.yaml 安全形态缺省、pytest 中心助手链一致。实现复用 _apply_test_targets(spec, [CODE_FIX_TEST_TARGETS_FALLBACK])——其对无占位符 spec 原样返回（零副本语义），可无条件调用。

## 双 spec 保留策略

定向判别依赖 _cmd_has_test_targets 识别原 spec（core/code_fix.py:2192），在 ctx 入口（约 :3464）盲替会杀掉判别。故：判别用原件、执行用消毒副本——_resolve_batch_regression_spec 的 :2187-2188 与 :2200-2204 两个回退出口返回消毒副本；重试轮路径（:3609-3612）改用消毒 spec 并纳入 _with_test_targets_env 窗口（或等效消毒），堵住「占位符在参数位 + 定向失败进重试」组合。该路径 mapped 真假两态共用 ctx 原件 reg_spec（:3611 的 subset_nodeids 分支只决定子集/全量，不换 spec），mapped 态同样字面透传——门面 _apply_pytest_subset（core/agent_runner/maintenance_runs.py:1622）只认既有收集目标、对字面占位符 fail-closed 无从替换，故两态统一消毒；消毒后 tests/ 成为可替换目标，mapped 态子集语义反而恢复。

## 范围裁决：周期回归豁免

core/admin_monitor.py:1708 周期回归定义上即全量、无 targets 概念，参数位占位符属配置错误而非框架义务；由 config.template 警示兜底，不入消毒范围。若未来该通道需定向化，另立条目。

## 兼容性与风险

- fenixd 自身安全形态（${FENIX_TEST_TARGETS:-tests/} 加 #{test_targets} 注释位）消毒后为无害 no-op：注释位替换不产生重复收集参数。
- 三个断言字面透传的存量测试（tests/test_code_fix_affinity_batching.py:557-563/:592-606/:609-615 assertIs）须按新语义改写，属验收一部分而非回归破坏。
- verify.yaml 13 行与「收口验证报告滞留」条目同源：一次提交两清，提交说明注明归属，防双登记双验收。