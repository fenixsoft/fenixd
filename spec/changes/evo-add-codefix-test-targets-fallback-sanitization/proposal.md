# add-codefix-test-targets-fallback-sanitization

## Why

{test_targets} 占位符语义由 add-codefix-affinity-batching 落地（替换 + 同值导出 FENIX_TEST_TARGETS 双轨），但只有定向分支调用 _apply_test_targets：三类回退出口（链末批恒全量、触碰面映射空集、定向配置关，core/code_fix.py:2187-2188/:2200-2204）与定向重试轮两态路径（:3609-3612，mapped 真假共用 ctx 原件 reg_spec）都把含占位符的命令原样交给 Popen（core/regression.py:805；mapped 态门面 _apply_pytest_subset 对字面占位符 fail-closed 无从替换）。naive 写法下占位符字面传给 pytest 必挂（exit 4 无 JUnit XML → parse_error 进重试 → 用原 spec 重跑仍挂 → 耗尽 targeted_retry_max 整批弃），且链末批挂则整链无法核销。fenixd 自身仅靠 verify.yaml 里 12 行未提交写法规约规避，其他接入项目无此防线；现有测试把字面透传断言为期望行为；config.template 的「安全样例」实为配置键文档、并无安全样例。

## What Changes

1. 回退路径消毒：模块常量 CODE_FIX_TEST_TARGETS_FALLBACK = tests/ 加薄包装（复用 _apply_test_targets，无占位符 spec 原样返回）；_resolve_batch_regression_spec 两个回退出口与重试轮两态路径（mapped 真假统一）返回/改用消毒副本；定向判别仍用原 spec（ctx 入口不盲替）。
2. 测试对齐：改写三个断言字面透传的存量测试；新增「占位符在场×三类回退」「重试轮两态消毒」「无占位符零迁移」「fenixd 安全注释形态无害」四组用例（str 与 list 两态）。
3. 配置规约落地：config.template targeted_regression 注释段补安全 cmd 样例与 MUST NOT 参数位警示；verify.yaml 工作区 13 行写法规约入库（与收口滞留清欠互引，一次提交两清）。
4. 周期回归通道（core/admin_monitor.py:1708）显式豁免：定义上即全量，参数位占位符属配置错误，由模板警示兜底。

## Non-Goals

- 不改定向分支行为（替换与 env 双轨维持现状，既有定向测试逐字全绿）。
- 不为周期回归通道做消毒（见 design 裁决）。
- 不改 {port} 先例语义与 FENIX_TEST_TARGETS 注入通道本身。

## Impact

- Specs: specs/codefix-test-targets-sanitization/spec.md（ADDED：回退路径占位符消毒、定向行为不变）
- Code: core/code_fix.py（常量、消毒包装、两个回退出口、重试轮路径）
- Tests: tests/test_code_fix_affinity_batching.py（改写 3 处 + 新增 4 组）
- Config: .fenix/config.template.yaml（安全样例与警示）、.fenix/verify.yaml（13 行写法规约入库）