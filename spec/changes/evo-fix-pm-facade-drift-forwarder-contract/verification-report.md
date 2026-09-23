# 验证报告：evo-fix-pm-facade-drift-forwarder-contract

> ⚠️ 本报告由框架于 2026-09-23T01:54:31Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-23T01:54:31.179924+00:00

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.44M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| drift-forwarder-runtime-probe | 「漂移预分类经门面可达」运行时正向探针：最小 PMEngine 实例经门面 __getattr__ 转发调 _preclassify_drift，与 queue.py:1267-1269 生产调用点同款五参位置传参（spec_name, result, impl_result, disputed, missing），branch=None 走 fail-open 返回 {"action": "fallback"}——修复前此处门面查表未命中抛 AttributeError→整轮派发回滚；并断言真身是 VAdjudicationMixin._preclassify_drift（adjudication.py:1087）。出处 core/pm_engine/engine.py:266、core/pm_engine/dispatch/queue.py:1267-1269 | pass | 0/2 | - |
| drift-forwarder-contract-tests-green | 注册条目契约回归（TestPreclassifyDriftForwarder 三用例）：条目逐字 ("_dispatcher", "_preclassify_drift") 且紧随 _preclassify_orphan（裁决组相邻）；经门面转发真身=Dispatcher/VAdjudicationMixin._preclassify_drift；五参签名与生产调用点一致。出处 core/pm_engine/engine.py:265-266、tests/test_pm_facade_forwarder_contract.py:149-187 | pass | 0/5 | - |
| drift-align-regression-green | 漂移机械对齐通道整体回归（回归点）：一行注册不得破坏漂移对齐既有行为，tests/test_deliverable_drift_align.py 全部 24 用例保持全绿。出处 core/pm_engine/dispatch/adjudication.py:1087（通道真身）、tests/test_deliverable_drift_align.py | pass | 0/2 | - |
| facade-call-site-coverage-green | 门面调用点覆盖性契约·正扫正向：core/ 下全部 self._pm.<name> 字面引用（调用与非调用访问）按目录分桶逐名可经对应门面解析 + 全部落桶无漏检（新组件门防漏检前提）。出处 tests/test_pm_facade_forwarder_contract.py:53-70（_BUCKETS）、:190-220 | pass | 0/4 | - |
| registry-reverse-assertion-green | 注册表反向断言正向（PMEngine 门）：全表二元组形态基线 + 每条目 (sub_attr, meth) 经惰性 property + getattr 链可解析（无悬空条目）+ 经门面 __getattr__ 端到端可解析。出处 core/pm_engine/engine.py:217-319、tests/test_pm_facade_forwarder_contract.py:226-250 | pass | 0/3 | - |
| three-registries-same-rule-green | 同构注册表同门·正向（spec Requirement「同构注册表同门检查」）：AgentRunner（runner.py:433，二元组与 self 首参模块函数并存）与 VerificationPipeline（pipeline.py:263，名: 模块函数单值）反向断言按条目形态分支适配、无悬空 + verification 侧现状零 self._pm._ 回引（书面说明，未来出现即失败）。出处 tests/test_pm_facade_forwarder_contract.py:252-306 | pass | 0/5 | - |
| legacy-forwarder-regression-green | 既有转发回归不回退（回归点）：本 SPEC 之前已存在的 AgentRunner 注册表断言 test_forwarder_registered_and_not_in_execute_agent 保持全绿（design Context：该断言原先只覆盖 AgentRunner 单名存在性，PMEngine 注册表此前零断言）。出处 tests/test_code_fix.py:1457 | pass | 0/3 | - |
| contract-suite-full-green | 全量收口（回归点/空状态）：契约测试文件 10 用例在真实验证树上零失败零错误（漂移转发 3 + 正扫 2 + 反扫/豁免 5），实测汇总行 "10 passed"。出处 tests/test_pm_facade_forwarder_contract.py（全文件） | pass | 0/3 | - |
| gate-catches-unregistered-call-site-pm-bucket | 硬门负路径·PMEngine 桶漏注册（spec Scenario「新增漏注册调用点被硬门拦截」）：monkeypatch 注入假调用点 self._pm._preclassify_typo_probe（core/pm_engine/zz_fake_probe.py:999，运行时 patch 扫描器、零磁盘侵入），契约正扫 MUST 失败且失败信息含缺失名与调用文件:行号。出处 tests/test_pm_facade_forwarder_contract.py:193-210 | pass | 0/2 | - |
| gate-catches-dangling-registry-entry | 硬门负路径·悬空条目（spec Scenario「悬空注册条目被反向断言拦截」）：monkeypatch 向 PMEngine 注册表注入 _ghost_entry_probe -> ("_dispatcher", "_ghost_method_probe")（指向不存在的子对象方法），反向断言 MUST 失败并输出条目键与目标。出处 tests/test_pm_facade_forwarder_contract.py:237-250 | pass | 0/2 | - |
| legitimate-non-registry-no-false-positive | 合法不入表名字不误报（spec Scenario「合法不入表名字不误报」）：门面显式定义（_queue_lock/_run_queue/_instant_fail_cooled/_get_config 等，含方法体内 self.<名> 实例属性赋值推导）与 verification/pipeline.py:356 静态式转发豁免清单（_extract_replan_error_items 等）均在解析域、确不经注册表（防腐化断言）。出处 tests/test_pm_facade_forwarder_contract.py:308-329 | pass | 0/3 | - |
| gate-catches-agent-runner-missing | 同门负路径·AgentRunner 桶分桶隔离性：注入 core/agent_runner/zz_fake_probe.py:999 假调用点 self._pm._not_a_facade_name_probe，分桶正扫 MUST 归 AgentRunner 门拦截并报告名字与文件:行号（liveness.py 等组件回引的是 AgentRunner，分桶归门防 PMEngine 门混扫误报）。出处 tests/test_pm_facade_forwarder_contract.py:53-56、:193-210、spec design D2 | pass | 0/2 | - |
| gate-catches-pipeline-form-drift | 同门负路径·反向断言形态适配：向 VerificationPipeline 单值表（名: 模块函数）混入二元组条目 _ghost_pipe_entry_probe -> ("_some_sub", "_ghost_meth")（PMEngine 形态混入），按形态分支的反向断言 MUST 拦截——(sub_attr, meth) 解包不可跨形态机械套用的形态基线真实生效。出处 tests/test_pm_facade_forwarder_contract.py:276-289、spec design Context | pass | 0/2 | - |
| gate-catches-unbucketed-new-component | 硬门负路径·分桶完备性：注入 core/newcomp_probe/zz.py:42 未分桶假调用点 self._pm._pm_probe_unbucketed，test_all_call_sites_are_bucketed MUST 拦截（core/ 新组件门 MUST 在 _BUCKETS 登记后纳入解析域检查，防漏检）。出处 tests/test_pm_facade_forwarder_contract.py:212-220 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

