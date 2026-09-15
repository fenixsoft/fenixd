# 验证报告：fix-command-main-serve-scope

> ⚠️ 本报告由框架于 2026-09-14T15:53:17Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-14T15:53:17.367752+00:00

## 结论：✅ 通过（verified）

**状态：verified — 7/7 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 7/7 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.56M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| serve-command-main-port-injection | 验证 command+main 契约实例路径（回归测试 test_command_main_placeholder_port_injection）：serve.kind=command 且 static_scope=main 时，{port} 注入 + rewrite_scenarios_origin 全量改写 + 就绪探针放行，legacy 兜底（_rewrite_scenario_port）不触发。运行 pytest 断言该用例通过。出处：tests/test_verify_command_port.py:269 | pass | 0/2 | - |
| serve-command-main-ownership-discovery | 验证 command+main 未引用 {port}（未迁移契约）经进程归属发现定位自绑默认端口（回归测试 test_command_main_unreferenced_port_ownership_discovery）：场景 origin 改写到自主端口并可达。运行 pytest 断言该用例通过。出处：tests/test_verify_command_port.py:311 | pass | 0/2 | - |
| serve-command-main-source-wiring | 源码级验证分派接线（design D2）：core/pm_engine/verification.py 新增 _serve_command_in_main 定义且 command+main 分支 return 调用它（不再穿透 legacy）。用 grep 断言方法定义与接线调用存在。出处：core/pm_engine/verification.py:603, core/pm_engine/verification.py:915 | pass | 0/3 | - |
| serve-command-main-source-cache-key | 源码级验证缓存策略（design D1）：_serve_command_in_main 以 spec_name 为键写入 _contract_static_servers、不含 head 缓存复用。grep 断言 cache[spec_name] 登记存在、head 缓存复用模式计数为 0。出处：core/pm_engine/verification.py:603-674 | pass | 0/3 | - |
| legacy-neutral-log-wording | 验证 legacy 兜底链端口改写日志归因措辞修正（回归测试 test_legacy_port_rewrite_log_no_planner_blame）：日志不含「planner 臆测」，为中性对齐措辞。运行 pytest 断言该用例通过。出处：tests/test_verify_command_port.py:364, core/pm_engine/verification.py:1070 | pass | 0/2 | - |
| legacy-neutral-source-grep | 源码级验证 legacy 归因措辞清理（tasks 2.1）：core/pm_engine/verification.py 中 legacy 改写日志与注释不含「臆测」误导归因措辞。grep 断言匹配计数为 0。出处：core/pm_engine/verification.py:1045, core/pm_engine/verification.py:2047 | pass | 0/2 | - |
| serve-scope-matrix-regression | 回归验证其余三条组合行为不变（spec serve-scope-matrix）：static×main、static×worktree、command×worktree 既有用例全部通过，command+main 新用例加入后整个 tests/test_verify_command_port.py 无失败。运行 pytest 断言全部 12 条通过。出处：tests/test_verify_command_port.py:124-334 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 7 个（第 1 轮）。

- 首轮写入 7 个场景

