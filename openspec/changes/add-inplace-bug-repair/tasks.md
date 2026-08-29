# Tasks: add-inplace-bug-repair

实现依据（实施 agent 必读）：
- 能力定义 `specs/inplace-bug-repair/spec.md` 与 `specs/verification-completion-gate/spec.md`（MODIFIED 增量）；设计决策 design.md D1-D5
- 现行派生入口：`.fenix/core/pm_engine.py` bug-found 处置与 `_ensure_fix_spec_files`（约 551-594 行）、族谱治理 `_fix_prefix_depth`
- 内部字段持久化机制：`.fenix/core/state_machine.py`（`_` 前缀字段写回 STATE.md）
- 依赖前置：add-verify-report-gate 已落地（报告存在性保障）

## 1. 原地打回处置

- [x] 1.1 bug-found（真实产品缺陷分流后）处置替换：递增 `_verify_fail_rounds` 并持久化；状态重置 bug-found → implementing；MUST NOT 调用 fix spec 派生
- [x] 1.2 tasks.md「`## 验证修复`」段注入：末尾追加或按轮数更新，引用 `openspec/changes/<spec>/verification-report.md` 与「真实产品 Bug」；不改写既有任务与勾选状态
- [x] 1.3 升级闸门：`_verify_fail_rounds` 达到模块常量阈值 3 → 状态置 blocked + human-escalation-alerts 告警（含 SPEC 名、轮数、报告路径），不再打回

## 2. legacy 兼容与退役

- [x] 2.1 「子 fix 完成 → 父 SPEC 自动重验」闭环标记 legacy，仅对存量 fix-* 链生效；新裁决路径不进入
- [x] 2.2 派生路径退役：新 bug-found 裁决不再派生 fix SPEC；存量 fix-* 链走保留的 legacy 闭环直至收敛，相关守卫/治理代码标记 legacy 隔离（族谱 governor 等死代码随存量链耗尽后移除）

## 3. 单元测试

- [x] 3.1 覆盖：首轮失败 → 计数 1 + implementing + 修复段注入 + 无新 fix spec；二轮失败 → 计数 2 + 段内轮数更新；第三轮 → blocked + 告警；计数器跨重启持久（模拟 STATE.md 重读）
- [x] 3.2 噪音分流不触发打回（assertion_results 为空场景）；既有勾选状态不被改写；存量 fix 链重验闭环回归测试

## 4. 验证与打包

- [x] 4.1 运行 `python3 -m pytest .fenix/tests/ -v` 确认无回归
- [x] 4.2 执行 `bash scripts/package.sh` 生成最新扩展包
