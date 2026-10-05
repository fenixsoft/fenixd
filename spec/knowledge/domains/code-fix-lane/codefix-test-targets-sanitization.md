# code-fix 回归占位符回退消毒

<!-- knowledge: capability=codefix-test-targets-sanitization rev=1
     sources=spec/archive/2026-10-06-evo-add-codefix-test-targets-fallback-sanitization -->

code-fix 批回归从定向退回全量或进入定向重试轮时的 `{test_targets}` 占位符消毒规则：回退执行的命令不得携带字面占位符。定向路径的替换与环境变量双轨语义本身见 [codefix-affinity-batching](codefix-affinity-batching.md)。

## 规则

- 消毒覆盖四条执行路径：链末批恒全量、触碰面映射空集回退、定向配置关回退（三类回退出口均返回消毒副本，分流语义 `targeted=False` 与原 spec 契约对象不改写），以及定向重试轮。命令含 `{test_targets}` 时执行前必消毒——str 形态原位替换为缺省 `tests/`；list 形态元素级替换（恰等占位符的元素展开为 `tests/`，内嵌形态 `dir={test_targets}` 原位替换为 `dir=tests/`，其余元素逐字保留）。消毒返回副本，不改写原 spec/cmd 对象。
- 无占位符零迁移：不含占位符的命令经消毒包装原样返回同一对象（零副本语义），回退行为逐字不变，因此可无条件调用消毒。
- 判别读原件、执行用消毒副本：定向判别（`_cmd_has_test_targets` 识别占位符声明）永远以 ctx 原件 spec 为准，消毒只发生在回退出口返回值与重试轮执行侧；MUST NOT 在 ctx 入口盲替——原件被预替换即杀掉定向判别。
- 定向重试轮两态统一消毒：mapped=True（失败明细可映射子集）与 mapped=False（回退全量）两态共用执行 spec，而回归门面对字面占位符 fail-closed 无从替换，必须先消毒再执行；消毒后 `tests/` 成为可替换收集目标，mapped 态子集语义随之恢复（`subset_nodeids` 语义不变）。
- 消毒缺省值为 `tests/`：与测试路径前缀识别、verify.yaml 安全形态缺省、pytest 中心助手链一致；剥离参数不可行——str 形态留双空格、list 内嵌形态产生 `dir=` 畸变、空收集走 rootdir 语义不可控。
- 周期回归通道（admin_monitor）显式豁免：该通道定义上即全量、无 targets 概念，参数位占位符属配置错误而非框架义务，由 config.template 警示兜底，不做消毒；该通道如需定向化必须另立条目。
- 配置规约：`{test_targets}` 只能出现在测试目标参数位之外的安全形态——config.template 的 targeted_regression 注释段提供安全 cmd 样例（`#{test_targets}` 注释位或 `${FENIX_TEST_TARGETS:-tests/}` env 缺省展开双轨写法）与 MUST NOT 直接写参数位的警示；fenixd 自身 verify.yaml 采用该安全形态，经消毒后为无害 no-op（注释位替换产物 pytest 不可见、不产生重复收集参数）。

## 关键行为

- 消毒截断的失败链：字面占位符传给 pytest → exit 4 无 JUnit XML → parse_error 进定向重试 → 用原 spec 重跑仍挂 → 耗尽 `targeted_retry_max` 整批弃；挂在链末批全量时整链无法核销。消毒在任何回退出口与重试轮入口生效，链不再被字面占位符引爆。

## 溯源

- 2026-10-06 evo-add-codefix-test-targets-fallback-sanitization（spec/archive/2026-10-06-evo-add-codefix-test-targets-fallback-sanitization） — 新建本页：三类回退出口与定向重试轮两态占位符消毒（缺省 tests/、零迁移、判别读原件执行用副本）、周期回归通道豁免、config.template 安全样例与参数位警示、verify.yaml 写法规约入库
