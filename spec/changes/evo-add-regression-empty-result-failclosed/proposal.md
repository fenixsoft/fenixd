# 提案：定向回归空结果 fail-closed 与 targets 消毒

## 背景

code-fix 批链合回前的定向回归按触碰面映射只跑相关测试，判定读 JUnit XML。2026-10-24T19:26:32Z 链 A 批 1 的回归命令因 targets 混入 #tests/__pycache__/*.pyc 缓存路径报 pytest usage error（exit=4、零用例执行、不写新 XML），判定分支（core/regression.py:985-993）按可解析的遗留 XML 判 passed，47 条台账修复在回归保证为空时合回（fenixd.log.3:35219→35225 闭环），且被放行批的目标含回归门自身测试。保留日志同形态 WARNING 累计 25 条、跨 13 个日期、连续 ≥5 个窗口复发；框架在案先例（maintenance_runs.py:2562-2564 引 a6e2fcc99c8a）证明形态早已已知但未修。

## 问题

- 判定缺「结果有效性」维度：core/regression.py:985-993 只要 XML 可解析且无失败即判 passed，退出码不参与改判，亦无 junit.xml 新鲜度校验。
- 定向 targets 无消毒：core/code_fix.py:2356-2370 _is_test_path 按 stem 放行 .pyc、:2447-2469 grep -rl 不排除 __pycache__、:2582-2589 输入无过滤。
- #{test_targets} 声明哨兵的 # 在替换后残留进执行命令（verify.yaml:126 声明、替换点 core/code_fix.py:2343/:2509），直接肇因 usage error。

## 目标

1. fail-closed 不变式：回归命令 returncode≠0 且解析 total=0 时，按 parse_error/infra 失败处理，MUST NOT 判 passed；叠加 junit.xml mtime 早于本次命令 started_at 的同判（新鲜度维度）。
2. 定向 targets 出入口消毒：过滤 # 前缀项、__pycache__/.pyc 路径与不存在路径，过滤留 WARNING 痕；消除 #{test_targets} 哨兵 # 残留。
3. 契约测试钉住「exit≠0＋total=0 不得 passed」「陈旧 XML 不得采信」与消毒行为。

## 非目标

- 不改 timeout 零失败面（在飞 evo-codefix-zero-face-regression-hardening 范围）。
- 不改回退路径消毒（已归档 add-codefix-test-targets-fallback-sanitization，其 Non-Goals 明文不改定向分支——本提案恰是其定向侧补全）。
- 不改 targets 合法时的判定行为与批次吞吐。

## 方案概述

core/regression.py 判定分支加双重守卫（returncode∧total 不变式优先，mtime 叠加）；core/code_fix.py 定向分支 targets 消毒与哨兵 # 残留消除；既有测试文件扩充契约用例（tests/test_regression_execution.py、tests/test_code_fix_affinity_batching.py 均已存在，直接增补）。
