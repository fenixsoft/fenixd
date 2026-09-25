# 提案：add-codefix-targeted-retry

## Why

code-fix 批回归失败后的重试 = 整批 agent 重做（实测 ~16min/批）+ 全量回归重跑（~10.2min），2026-09-24~09-25 窗口发生 8 次，浪费约 3.4 小时。且失败用例明细不落盘——重试 prompt 只拿到无结构摘要，事后也无法区分「真缺陷」与「测试自身缺陷/抖动」。

## What Changes

- **MODIFIED** `code-fix-lane` 的回归门与重试语义：回归失败后的重试轮从「整批 items 重做 + 全量回归重跑」改为「定向修复 + 失败用例子集重跑」
- 新增定向重试轮（上限可配置 `admin.code_review_fix.targeted_retry_max`，缺省 3）：prompt 注入结构化失败用例明细，agent 只修复与失败用例相关的问题；修复对象可以是产品代码，也可以是测试本身（断言过时、替身失真、超时替身自旋类），由 agent 依据用例信息判定
- 回归失败用例明细结构化落盘（nodeid + 失败摘要），供重试注入与事后审计
- 定向轮耗尽仍失败 → 沿用既有「现场即弃入失败档案」收尾语义（预算、锁释放、链继续，均不变）

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `code-fix-lane`（活源：`spec/changes/add-code-fix-batch-failure-selfheal/specs/code-fix-lane/spec.md`）：「全量回归门与合回」requirement 的重试轮回归范围从全量改为失败子集；新增「定向重试轮」requirement

## Impact

- `core/code_fix.py`：重试循环改造（≤3 轮、累计失败注入、子集回归）
- `core/agent_runner/maintenance_runs.py`（或 `run_regression` 原语层）：支持用例子集执行
- `agents/code-fix.md`：定向修复契约段（只修失败相关、可修测试、`fix_scope=test` 标注、禁止扩面重做全批）
- `.fenix/config.template.yaml`：新增 `targeted_retry_max` 配置键
- 边界：跨轮的「回归失败 → 台账条目（`regression-` 前缀、复发重开）」由 add-regression-auto-fix 负责；本 SPEC 只治理批内重试轮，二者正交
