# 验证报告：evo-add-codefix-test-targets-fallback-sanitization

> ⚠️ 本报告由框架于 2026-09-28T19:32:48Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-28T19:32:48.475649+00:00

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.25M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| sanitize-fallback-exits-str | 占位符在场（str 形态）×三类回退出口：模块常量 CODE_FIX_TEST_TARGETS_FALLBACK=tests/ 在场，链末批恒全量、触碰面映射空集、定向配置关三个回退出口均返回消毒副本（占位符替换为 tests/），分流语义（targeted=False）与原 spec 契约对象不被改写；含占位符独占命令边界（消毒后恰为 tests/）。出处 core/code_fix.py:2185-2215（_resolve_batch_regression_spec）、:1232/:1361（占位符常量与 _apply_test_targets） | pass | 0/7 | - |
| sanitize-fallback-exits-list | 占位符在场（list/argv 形态）×三类回退出口：占位元素恰等占位符展开为 tests/（元素级替换），内嵌形态 dir={test_targets} 原位替换为 dir=tests/（非剥离畸变），其余元素逐字保留，原 cmd 不被原地改写。出处 core/code_fix.py:1361-1397（_apply_test_targets list 两态语义）、design「消毒缺省值选型」 | pass | 0/6 | - |
| zero-migration-no-placeholder | 无占位符零迁移：不含占位符的 cmd（str 与 list 两态）经三类回退出口均原样返回同一对象（零副本），命令逐字不变，回退行为与改动前一致。出处 specs/codefix-test-targets-sanitization「Scenario: 无占位符零迁移」、design「可无条件调用」 | pass | 0/5 | - |
| targeted-path-behavior-unchanged | 定向路径行为不变：非末批+配置开+占位符+映射非空仍替换为触碰面映射目标 tests/test_foo.py（而非回退缺省 tests/），返回副本不改写原对象；定向判别依据（原 spec 的占位符声明）不被预替换。出处 core/code_fix.py:2203-2209（定向分支）、:1349（_cmd_has_test_targets 判别）、specs「Scenario: 定向场景逐字回归」 | pass | 0/3 | - |
| retry-round-sanitize-mapped-subset | 定向重试轮 mapped=True 态消毒（str 形态）：stub runner 驱动 _run_batch_created 首轮回归失败（junit 明细可映射）→ 定向重试轮的 run_regression 收到消毒 spec（pytest tests/ …，无字面占位符），且 subset_nodeids 仍为失败用例 nodeids（子集语义保持）。出处 core/code_fix.py:3617-3621（重试轮现状字面透传点 reg_spec）、design「双 spec 保留策略」 | pass | 0/4 | - |
| retry-round-sanitize-unmapped-full | 定向重试轮 mapped=False 态消毒（list 形态）：首轮回归失败且无结构化明细（fallback_full）→ 重试轮回退全量，收到消毒 spec（占位元素替换为 tests/）且 subset_nodeids=None（全量语义保持）。出处 core/code_fix.py:3609-3612（mapped 真假共用 ctx 原件 reg_spec）、:724-757（_ingest_failure_round fallback_full） | pass | 0/4 | - |
| safe-comment-form-noop-shell-exec | fenixd 安全注释形态无害：${FENIX_TEST_TARGETS:-tests/} 加 #{test_targets} 注释位的 verify.yaml 写法经回退消毒后，注释位被替换为 #tests/（词首注释 pytest 不可见）、不产生重复收集参数，回退窗口（FENIX_TEST_TARGETS 不在场）shell 实跑恰收集 1 例通过。出处 .fenix/verify.yaml regression.cmd 安全形态（工作区 13 行写法）、design「兼容性与风险」 | pass | 0/5 | - |
| delivered-test-suite-green | 交付测试套件全绿（回归点）：tests/test_code_fix_affinity_batching.py 以 -v 运行（不并列 -q），改写的 3 处存量透传断言与新增四组用例全部通过（exit 0 + PASSED 行 + passed 汇总）。出处 tests/test_code_fix_affinity_batching.py:557-632（存量三处 assertIs 改写点）、tasks 2.1/2.2 | pass | 0/3 | - |
| delivered-new-test-groups-present | 交付测试四组新增用例在场：ast 枚举 tests/test_code_fix_affinity_batching.py 的 test_ 函数（基线 37 个），新增后总数 ≥41（占位符×三类回退、重试轮两态消毒、无占位符零迁移、安全注释形态无害，每组覆盖 str/list 两态），并列出全部用例名供审计。出处 tasks 2.2、proposal「测试对齐」 | pass | 0/3 | - |
| config-template-safety-guidance | 配置规约落地（config.template）：targeted_regression 注释段含 MUST NOT 把 {test_targets} 直接写进参数位的警示，并补安全 cmd 写法样例（#{test_targets} 注释位或 ${FENIX_TEST_TARGETS:-…} env 缺省展开形态），纠正原 :471 引导写占位符的表述。出处 .fenix/config.template.yaml:466-476、tasks 3.1 | pass | 0/2 | - |
| verify-yaml-convention-committed | 配置规约落地（verify.yaml 入库）：regression.cmd 采用 ${FENIX_TEST_TARGETS:-tests/} env 缺省展开 + #{test_targets} 注释位双轨写法（YAML 解析后注释位仍在场＝整体加引号入库的间接证明），文件含 MUST NOT 参数位警示的写法规约。出处 .fenix/verify.yaml:101-105（现状裸 cmd）、tasks 3.2（git diff 实测 +12/-1） | pass | 0/3 | - |
| regression-facade-end-to-end-sanitized | 消毒 spec 端到端（交互流程 + 回归点）：安全形态 cmd 经映射空集回退消毒后，传入真实 run_regression 门面在隔离夹具执行——全量通过且收集 2 例；再以失败 nodeids 子集回归通过且只跑 1 例（消毒后 tests/ 成为可替换收集目标，mapped 态子集语义恢复）。出处 core/agent_runner/maintenance_runs.py:1685（run_regression 门面）、:1622（_apply_pytest_subset）、design「mapped 态子集语义反而恢复」 | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

