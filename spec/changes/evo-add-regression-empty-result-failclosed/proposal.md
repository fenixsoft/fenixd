# 提案：定向回归空结果 fail-closed 与 targets 消毒

## 背景

code-fix 批链合回前的定向回归按触碰面映射只跑相关测试，判定读 JUnit XML。2026-10-24T19:26:32Z 链 A 批 1 的回归命令因 targets 混入 tests/__pycache__/*.pyc 缓存路径报 pytest usage error（exit=4、零用例执行、落 0 例 XML），判定分支（core/regression.py:1012-1036，拟判 :1017-1020）只看解析结果、退出码不参与改判，exit=4 下可解析的 0 例 XML 仍判 passed（fenixd.log.3:35219-35220「按解析结果判 passed」+「status=passed, total=0」即证），47 条台账修复在回归保证为空时合回（fenixd.log.3:35219→35225 闭环），且被放行批的目标含回归门自身测试。targets 实际注入通道是 cmd 声明内 ${FENIX_TEST_TARGETS:-tests/} 环境变量（verify.yaml:126；词首哨兵 # 是行内注释、pytest 不可见），毒化 .pyc 经该通道进入 pytest。保留日志同形态 WARNING 按 MERGE-NOTES 终裁口径累计 30 次（10-04~10-29，retained log.4=1＋log.3=24＋log=5）；框架在案先例（core/agent_runner/maintenance_runs.py:2684-2707 注 a6e2fcc99c8a，「XML 零用例且无失败仍落 passed，回归假通过」见 :2703-2704）证明形态早已已知但未修。

## 问题

- 判定缺「结果有效性」维度：core/regression.py:1012-1036（拟判 :1017-1020）只要 XML 可解析且无失败即判 passed，退出码不参与改判（:1015-1016 注释自认），亦无 junit.xml 新鲜度校验。
- 定向 targets 无消毒：core/code_fix.py:2382-2396 _is_test_path 经 :2389 tests/ 前缀支放行 tests/__pycache__/*.pyc、:2473-2495 grep -rlE 不排除 __pycache__、:2528（cmd 替换入参）与 :2577（FENIX_TEST_TARGETS 导出值）均无过滤——两条注入通道任留其一即毒化可达（本案实测肇因即 env 通道）。
- #{test_targets} 声明哨兵的 # 在替换后残留进执行命令（verify.yaml:126 声明、替换点 core/code_fix.py:2535/:2555）：该残留居词首注释位、pytest 不可见（verify.yaml:118-119 自证），并非本案 usage error 的直接肇因（直接肇因是 env 通道注入的 .pyc），但替换值含引号字符时引号会击穿注释语义、使 # 目标成为 pytest 参数，属应消除的毒化面。

## 目标

1. fail-closed 不变式：回归命令 returncode≠0 且解析 total=0 时，按 parse_error/infra 失败处理，MUST NOT 判 passed；叠加 junit.xml mtime 早于本次命令 started_at 的同判（新鲜度维度）。
2. 定向 targets 出入口消毒：在单点 producer（_map_fix_files_to_tests 产出处，或调用点 core/code_fix.py:4152 拿到 targets 后即刻）过滤 # 前缀项、__pycache__/.pyc 路径与不存在路径，过滤留 WARNING 痕，使 cmd 替换与 FENIX_TEST_TARGETS 环境变量两条注入通道同享消毒后列表；消除 #{test_targets} 哨兵 # 残留。
3. 契约测试钉住「exit≠0＋total=0 不得 passed」「陈旧 XML 不得采信」与消毒行为。

## 非目标

- 不改 timeout 零失败面（在飞 evo-codefix-zero-face-regression-hardening 范围）。
- 不改回退路径消毒（已归档 add-codefix-test-targets-fallback-sanitization，其 Non-Goals 明文不改定向分支——本提案恰是其定向侧补全）。
- 不改「targets 合法且命令真实执行产出新鲜非空结果」时的判定行为与批次吞吐（空结果 total=0 形态按目标 1 收口，含合法 targets 零收集 rc=5 形态——伪绿转失败是明示取舍）。

## 方案概述

core/regression.py 判定分支加双重守卫（returncode∧total 不变式优先，mtime 叠加）；core/code_fix.py 定向分支 targets 消毒与哨兵 # 残留消除；既有测试文件扩充契约用例（tests/test_regression_execution.py、tests/test_code_fix_affinity_batching.py 均已存在，直接增补）。
