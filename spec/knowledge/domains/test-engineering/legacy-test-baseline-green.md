<!-- knowledge: capability=legacy-test-baseline-green rev=1 sources=spec/changes/fix-legacy-test-failures -->

# 主线全量测试零失败基线

主线全量测试套件的基线契约与失败处置纪律：全量 0 failed 是所有以「通过所有单元测试」为验收口径的后续 SPEC 成立的前提，任何失败修复须可追溯归因且不掩盖真实缺陷。

## 现行规则

- 基线契约：`python3 -m pytest tests/ -q` 以 0 failed 收场（passed/skipped/xfail 均可接受）。全量执行走有界入口 `bin/run_full_suite.py`（主机级互斥锁，套件量级约 1 万用例、单轮约 12 分钟）；基线稳定性以间隔执行的两轮全量均 0 failed 为准，单轮全绿不作为 flaky 排除依据。
- 归因强制四类：每个被处置的失败须带可追溯归因并落处置任务说明——`[违例]` 修实现；`[断言]` 修断言，仅在复核确认现行行为正确时使用，须注明「断言脱节」归因与复核证据；`[隔离]` 修测试自身的隔离与确定性（顺序依赖/共享状态/时序敏感）；`[WIP]` 干净分支不复现即关闭，不改任何代码。
- 干净分支复现门：动手修复前，先在从 HEAD 切出的干净实现分支上以单测节点级复现该失败；复现才修，不复现按 `[WIP]`/`[隔离]` 归因关闭。并发会话共用的工作树含他 SPEC 的 WIP 时，全量基线的失败数字不具权威性——失败可能由并发 WIP 诱发而非实现缺陷，不得据其直接立项修复。
- 反掩盖不变量：不允许以删除测试、放宽守卫或无归因改断言使套件变绿；守卫测试本体与白名单不因清零诉求改动，真实违例一律修实现。同簇多个失败先收敛共同根因再修，禁止逐测试打补丁。
- 新失败同款纪律：基线之外出现的新失败按同一套复现门 + 归因纪律处置，处置不得删除或放宽既有测试。
- 验收证据：处置收口的全量结果（两轮）归档 `.fenix/verify-evidence/<SPEC名>/` 摘要 JSON，归因与证据逐条落 tasks 任务说明，不经记忆转述。

## 关键行为

单轮失败处置流程：干净分支单测节点复现 → 归因（违例/断言/隔离/WIP 四类）→ 复现者按归因修复（修实现优先，断言修附复核证据）→ 对应测试文件回归确认 → 有界入口全量两轮（间隔执行）0 failed 收口。守卫类失败（替身签名保真、logger 旁路、调用点参数等静态守卫）按守卫自身纪律修复违规测试本体，守卫与白名单零改动。

## 代码锚点

- 验收入口：`bin/run_full_suite.py`（主机级全量互斥与有界超时）
- 守卫测试：`tests/test_fake_double_fidelity.py`（替身签名保真守卫）、`tests/test_logger_no_bypass.py`（core 裸 getLogger 守卫）
- 违例修复落点：`core/dsh_session_tidy.py`（层级日志名对齐 `fenixd.` 前缀）、`core/logger.py`（全局 fenixd 根日志器传播挂载点）

## 溯源

- 2026-11-10 fix-legacy-test-failures（spec/changes/fix-legacy-test-failures/） — 新建本页：确立全量 0 failed 基线契约、干净分支复现门、归因四类纪律与反掩盖不变量。基线 11 项存量失败经复现门归因：9 项 WIP 关闭（并发工作树诱发、零代码改动），2 项真实修复（替身签名显式化 13 处、core 日志层级名 1 处），全量两轮实测 0 failed；为 add-platform-abstraction-layer 全绿验收口径的前置基线（其调度依赖以该 SPEC `.spec.yaml` 的 `depends_on` 登记为准）
