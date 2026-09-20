# 验证报告：refactor-facade-delegation

> ⚠️ 本报告由框架于 2026-09-17T22:00:02Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-17T22:00:02.818328+00:00

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.18M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-facade-import-compat | 收敛后既有导入路径不变：from core.pm_engine import PMEngine / core.pm_engine.verification import VerificationPipeline / core.agent_runner import AgentRunner 及注册表目标子模块类均可导入（spec：导入路径不变 / 调用路径兼容） | pass | 0/2 | - |
| cli-inventory-artifact | 阶段 0 交付物 facade-inventory.md 存在且含形态二分标注：3 组「实例式转发」/3 组「静态式转发」标题 + 收敛对象总数 267（design D6 / 阶段 0 权威清单） | pass | 0/4 | - |
| cli-tasks-symbol-anchors | 任务锚点为符号名：tasks.md 无「第 N 行」式绝对行号锚点，方法名/机制名锚点（__getattr__/_FORWARDER_REGISTRY/staticmethod）数量>0（spec：任务锚点为符号名 / D6 不使用绝对行号锚定） | pass | 0/4 | - |
| cli-forwarder-registry-converged | 转发方法被消除或去重：AST 重扫三宿主类剩余「单条 return self.<子对象>.<方法>/self.<方法>」委托方法数=0；_FORWARDER_REGISTRY 长度 100/85/52、staticmethod 类级别名 10/5/15 与 facade-inventory.md 权威清单一致（spec：转发方法被消除或去重 / D2 注册表形态 / D7 类级别名） | pass | 0/6 | - |
| cli-static-class-direct-calls | 静态式转发类直调仍可用且实例路径不注入 self：VerificationPipeline._normalize_fail_signature/_replan_errors_unconsumed/_extract_replan_error_items、AgentRunner.parse_api_error_status/classify_switch_error/_entry_is_tool_result、PMEngine._is_fix_spec 等 D1 约束 4 实测点类直调返回与重构前一致；self._extract_replan_error_items(env_error) 实参不被追加 self（spec：静态方法式转发的类直调仍可用 / 实例路径调用参数不被二次注入） | pass | 0/2 | - |
| cli-double-signature-eliminated | 双份签名不再存在：8 个采样转发名在 core/ 全仓 def 恰 1 处（仅子模块实现处），门面文件已无同名 def 方法体（spec：双份签名不再存在 / D7 别名无签名无 docstring） | pass | 0/2 | - |
| cli-instance-path-return-equiv | 门面实例路径委托返回值不变：经 __getattr__ 委托的 pipe._normalize_fail_signature/_extract_replan_error_items/_replan_errors_unconsumed、runner._entry_is_tool_result/parse_api_error_status、PMEngine._normalize_fail_signature（链式别名→VerificationPipeline）对同输入返回与重构前一致结果（spec：返回值不变 / 零行为变化） | pass | 0/2 | - |
| cli-patch-gap-semantics | patch 语义保持：patch.object(facade, X) 与 patch.object(facade.<子对象>, X) 两种缝隙均生效且退出恢复转发、monkeypatch 实例替换 _now 可用（spec：字符串路径 patch 语义保持 / design D3 缝隙兼容性论证） | pass | 0/2 | - |
| cli-contract-tests-green | 契约测试 28 项 544 子断言全绿：tests/test_facade_delegation_contract.py 逐名解析同一函数/未知名 AttributeError/dunder 不转发/静态组不被 partial 覆盖/类直调组/覆盖性硬门 270 名全集（design D4 / spec Scenarios 1-4,8,9 的测试层锁定） | pass | 0/7 | - |
| cli-callsite-direct-test-files | 类直调调用点不残留断链：D1 约束 4 实测类直调点所在 5 个测试文件（test_frozen_scenario_reservoir/test_run_cancel/test_provider_circuit/test_provider_failover/test_repair_lane_dedup）复跑全绿（spec：类直调调用点不残留断链 / 调用点无残留断链） | pass | 0/2 | - |
| cli-static-guards-green | 静态守卫适配后全绿：test_callsite_arity_guard + test_fake_double_fidelity 24 用例通过；seam 集合变化（F-13：_check_agent_result_artifact 转出类 seam）为守卫基准调整而非产品行为变化（design 5.4 / 阶段 4 全量复核） | pass | 0/2 | - |
| cli-full-suite-baseline | 全量回归不引入新失败：bin/run_full_suite.py --baseline HEAD 对比基线，失败集合归类为存量或全绿、无「本次引入」、无挂起（spec：全量测试不引入新失败 / 阶段 4 全量回归） | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

