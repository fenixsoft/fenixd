# 验证报告：evo-add-regression-empty-result-failclosed

> ⚠️ 本报告由框架于 2026-10-30T11:10:42Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T11:10:40.486602+00:00+run-result@mtime1793358640526712940

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.38M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| reg-exit4-zero-total-failclosed | R1 空结果 fail-closed（pytest usage error 形态）：构造回归命令写「新鲜 0 例 JUnit XML」后以 exit=4 退出，驱动真实 run_and_write_regression 判定——status 必须为 parse_error（不得判 passed）、reason 非空、WARNING 留痕注明 empty_result 形态、回归快照落盘同为 parse_error（批次收尾语义）。出处：core/regression.py:1012-1048 判定分支（:1017-1020 拟判 passed、:1041-1047 既有豁免 WARNING 即本案伪绿通道）、:901 started_at 取时点 | pass | 0/6 | - |
| reg-exit5-zero-total-failclosed | R1 零收集形态：回归命令写 0 例 XML 后以 exit=5（pytest 零收集）退出，判定同 R1——status 必须为 parse_error 不得 passed，WARNING 注明 empty_result 形态。出处：core/regression.py:1012-1048；specs/codefix-regression-guard/spec.md 行为约束（合法 targets 零收集 rc=5+total=0 伪绿转失败是明示取舍） | pass | 0/5 | - |
| reg-stale-xml-failclosed | R2 结果新鲜度：回归命令写 1 例全绿 XML 后把 junit.xml mtime 回拨 3600s（早于本次命令 started_at）且 exit=0，判定不得采信陈旧结果——status 必须为 parse_error 且 WARNING 注明 stale_xml 形态。出处：core/regression.py:889-899 预清理 unlink OSError 被吞后遗留旧 XML 被采信的残余洞、:901 started_at 取时点 | pass | 0/4 | - |
| reg-nonzero-exit-fresh-nonzero-exemption | 既有豁免不回归：命令写「新鲜 1 例全绿 XML」后 exit=1（runner 收尾崩溃形态），判定仍必须 passed 且结果附 exit_code=1 结构化留痕——R1 fail-closed 守卫不得误伤「XML 新鲜且 total>0 的收尾崩溃」豁免。出处：core/regression.py:1037-1047 | pass | 0/5 | - |
| reg-normal-pass-unchanged | 正常路径不变式：exit=0 且新鲜 1 例全绿 XML → status=passed、total=1、passed=1，判定行为零变化（R1/R2 守卫不得对合法新鲜非空结果误报）。出处：core/regression.py:1012-1036 既有判定分支 | pass | 0/5 | - |
| targets-poisoned-dual-channel-sanitized | R3 定向 targets 消毒·双通道同源：fix-out 产物行混入 tests/__pycache__/*.pyc、# 前缀项与不存在路径（连同合法 tests/test_real.py），经 _resolve_batch_regression_spec 产出定向 spec 与 targets——cmd 占位符替换与 FENIX_TEST_TARGETS 环境变量导出两条注入通道必须同享消毒后列表：毒化项零残留、合法项保留、定向仍成立，且被过滤项有 WARNING 留痕。出处：core/code_fix.py:4233-4282（:4262 映射调用点）、:2537-2541 cmd 替换、:2570-2599 env 导出、:2426-2502 _map_fix_files_to_tests | pass | 0/10 | - |
| targets-all-poisoned-falls-back-full | R3 消毒后空集回退全量：fix-out 产物行仅含毒化项（.pyc/#前缀/不存在路径）时，消毒后 targets 空集必须沿用既有 fail-open 回退全量语义（_sanitize_test_targets 以 tests/ 替换占位符）——不以空 targets 起跑、cmd 零毒化残留零哨兵 # 残留。出处：core/code_fix.py:2602-2611 _sanitize_test_targets、:4265 定向判别分支 | pass | 0/6 | - |
| istestpath-excludes-pycache-pyc | R3 tests/ 前缀判别收口：_is_test_path 对 tests/__pycache__/ 段与 .pyc 文件必须返回 False（现状 :2395 tests/ 前缀支先于一切判别放行 .pyc 即毒化面），对真实测试文件保持 True 不误伤。出处：core/code_fix.py:2388-2402 | pass | 0/9 | - |
| grep-lookup-excludes-pycache-binary | R3 grep 反查消毒：触碰面映射的产品文件 import/from 反查不得命中 tests/__pycache__/ 下的二进制 .pyc 与任何 __pycache__ 文件，仍命中真实 tests/test_foo.py——grep -rlE 需加 -I 与 --exclude-dir=__pycache__。出处：core/code_fix.py:2479-2501（:2486-2493 grep 调用） | pass | 0/4 | - |
| sentinel-hash-not-residual | R4 哨兵残留消除：对 .fenix/verify.yaml:126 声明形态 cmd（尾部 #{test_targets} 词首注释哨兵）做占位符替换后，最终执行命令必须零 # 残留（吞掉紧邻 # 或替换值层规范化）、占位符消费完毕、_cmd_has_test_targets 对原 spec 探测仍 True 不受影响、str/list 两态替换点行为不变。出处：core/code_fix.py:2505-2514、:2537-2541（str 替换）、:2544-2563（list 替换） | pass | 0/9 | - |
| legit-targets-behavior-unchanged | 行为约束·合法 targets 不变式：合法 targets 列表替换后 cmd 含两个目标且占位符消费完毕、原 spec 不可变（dataclasses.replace 副本语义）、FENIX_TEST_TARGETS 导出值与 cmd 替换值同源一致、空 targets 时 spec 原样返回（零副本）。出处：core/code_fix.py:2517-2567、:2570-2599 | pass | 0/7 | - |
| contract-tests-regression-execution-green | 任务 3.1 契约测试套件通过：pytest tests/test_regression_execution.py 全绿——含新增「exit≠0＋total=0 不得 passed」（usage error exit=4 形态）与「mtime 早于 started_at 的陈旧 XML 不得采信」契约用例，且「XML 新鲜且 total>0 的非零退出仍 passed」既有豁免用例零回归 | pass | 0/2 | - |
| contract-tests-codefix-affinity-green | 任务 3.2 契约测试套件通过：pytest tests/test_code_fix_affinity_batching.py 全绿——含消毒用例（# 前缀/__pycache__/.pyc/不存在路径被过滤且留痕、env 导出值与 cmd 替换同源消毒、合法 targets 判定行为不变），既有用例零回归 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

