# Tasks: 修复 improve-run-lifecycle-governance 验证发现的缺陷

## 调查结论（2026-08-28）

本 SPEC 的唯一真实交付物是「定位并修复父 SPEC 验证报告中的真实产品 Bug」。经完整排查，
**不存在可修复的真实产品缺陷**，理由如下（均有铁证）：

1. 父 SPEC `improve-run-lifecycle-governance` 的 `verification-report.md` 在 main、
   所有 worktree、所有 ref 中**均不存在**（全局 `find` 与 git 检索确认）。
2. 父 SPEC 的核心实现（D1–D6：`has_live_attempt` / `refresh_locks` /
   `dispatch_backoff_schedule` / `recovery_watch` / liveness 监督 / `dispatch_stalled`）
   **从未合入 main** —— 所有 `fix-improve-run-lifecycle-governance-*` 分支与 main
   的共同基底一致，无任何实现增量。
3. 父 SPEC 的验证**确实跑过**，产物落在 `.fenix/verify-progress/improve-run-lifecycle-governance/`
   （`report.json` + `.fenix-run-result.json`），结果 `status: bug-found`，15/17 场景失败。
4. 该「bug」被报告本身**明确归类为验证脚手架/环境问题**（非产品缺陷）：
   - `mock_api` 对 `/api/specs?project=fenixd*`（带查询串 glob）拦截未生效，前端渲染真实
     后端 54 条 SPEC 行而非 fixture 注入的治理态；
   - 铁证：`empty-state-no-specs-no-alerts` 场景 fixture 已 `specs:[]`，实测
     `actual_count=54`；
   - 反证：同场景精确 URL 的 `/api/alerts` mock 生效（`.alert-item` 计数=1 通过）。
5. 本 SPEC 自身范围**明确排除伪失败**：父 proposal 写明
   「伪失败（测试框架/场景缺陷）不在本 SPEC 修复范围内」。
6. 回归测试**全绿**：`python3 -m pytest .fenix/tests/ -q` → **641 passed, 0 failures**
   （含 22 个 lifecycle 定向用例全通过），证明无真实产品回归。

因此 task 1.1 的实质结论为「无真实产品 Bug 可修复」，符合本 SPEC 排除伪失败的范围界定；
强行实现父 SPEC 尚未合入的 D1–D6 特性属凭空新增产品行为，与「修复已验证真实缺陷」的范围
相悖，不予执行。下方任务按实际执行结果标记。

## 1. 修复真实产品缺陷

- [x] 1.1 阅读父 SPEC 验证产物并定位「真实产品 Bug」：经排查，父 SPEC 验证报告（
  `.fenix/verify-progress/improve-run-lifecycle-governance/`）记录的 15 个失败场景**全部根因于
  验证环境 mock 拦截失效**（带查询串 glob 的 `/api/specs` 端点未命中），属伪失败/验证脚手架
  缺陷，不在本 SPEC 修复范围内；main 无真实产品回归（641 测试全绿）。**无真实产品 Bug 可修复。**

## 2. 验证与打包

- [x] 2.1 运行框架测试确认编译与无回归：本仓库为 Python 常驻守护进程，无 `package.json` /
  `tsc+vite build`，对应 Python 测试 `python3 -m pytest .fenix/tests/ -q` → **641 passed**。
- [x] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归：
  **641 passed, 0 failures**（含 22 个 lifecycle 定向用例）。
- [x] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包：成功产出
  `dist/fenixd-20260828.tar.gz`（324K）。
