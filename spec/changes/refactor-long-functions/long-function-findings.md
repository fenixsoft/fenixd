# Long Function Findings（疑点清单）

> design Non-Goal：「不顺手修 bug——只记疑点清单」。本文档只记录不修；
> 每项附符号锚点（design D8：不使用绝对行号锚定）与观察证据，供后续 spec 评估。

## P1. pipeline：`_run_three_stage_verification`

### F1-1 `_verify_modules` 清单为硬编码字面量，未随引擎子模块增删自愈
- 锚点：`_verify_modules`（B0，函数体内 importlib.reload 列表）
- 现象：10 个模块名硬编码在函数体内；新增 verify_engine 子模块须手动加入。
- 影响：低。reload 是热更新保障，漏载只影响常驻进程热更新，不影响首次导入。
- 建议：改为 `pkgutil.iter_modules(core.verify_engine.__path__)` 动态枚举（后续 spec 评估）。

### F1-2 reload 失败静默降级为 warning，无集中失败信号
- 锚点：B0 `except Exception` 分支（`self._context.logger.warning`）
- 现象：任一模块 reload 失败仅 warning 留痕，流程继续用旧代码；多个模块同时失败
  无法从单点信号发现。
- 影响：低-中。属既有设计（admin 热更新保障的兜底），但多模块连锁失败时
  诊断成本高。
- 建议：保留（fail-open 是刻意行为），后续可考虑失败计数告警。

### F1-3 `while True` 循环 472 行 + 10 处 return，无循环不变式文档
- 锚点：B2/B3 循环体
- 现象：循环体内部 3 处 continue / 1 处 break / 10 处 return，无循环不变式注释；
  `report`/`app_reachable`/`reach_note` 等循环变量在体内多次重写。
- 影响：中（可维护性）。等价搬移时须严格按 D2 边界，不得重组。
- 建议：本变更按 D2 保留循环体；后续 spec 可评估状态机重构（已有替代方案否决记录）。

### F1-4 `_stage1_status` 与 `_entry_status` 双入口检查冗余但语义不同
- 锚点：`_entry_status`（B0）/ `_stage1_status`（B2 planner 派发前）
- 现象：两处状态检查判据相同（`!= "testing"` → 丢弃），但注释说明针对不同竞态
  （入口漂移 vs fast-track 孤儿 run）。
- 影响：低。语义已区分（B0=入口丢弃；B2=planner 派发前重查），非 bug。
- 建议：保留，不合并。

## P2. runner：`_execute_agent_inner`

### F2-1 frozen 早退路径不登记 `used_wts`/`handed_off` 但返回 `worktree_kept`
- 锚点：R1 frozen 分支（`return AgentRunResult(... worktree_path=kept_wt_path ...)`）
- 现象：frozen 分支直接 return，未经过终态收割（外层 finally 仍会收）；若
  `kept_wt_path` 为 None，`worktree_kept=False` 一致；但若此前 attempt 已置
  `kept_wt_path`（理论不可能——frozen 检查在 attempt 顶部），语义无碍。
- 影响：低。frozen 在 attempt 顶部检查，kept_wt_path 必为 None。
- 建议：观察项，非 bug。

### F2-2 cancel 分支 worktree 三型处置中 `repair` 复用 keep 语义
- 锚点：R1 cancel 分支（`elif agent_type == "repair": kept_wt_path = wt_path; handed_off.add(wt_path)`）
- 现象：cancel 时 repair 车道 keep worktree（供 dispatch 层 fallback 清理），
  而其它车道 cleanup——语义已注释，但 repair 车道 cancel 保留现场是否应
  显式标记 `_cancelled_hold` 存疑。
- 影响：低-中。观察项。
- 建议：保留（既有设计），后续 spec 评估 cancel 语义一致性。

### F2-3 `chain_cursor` 在 R7 成功终态被重写（`chain_cursor` 写点跨 R0/R2/R7）
- 锚点：R7（成功终态）`chain_cursor` 写点
- 现象：D3 状态对象须逐字段映射读写点，`chain_cursor` 跨三块写，
  提取时须保证写序不变（先 R2 推进，R7 复核）。
- 影响：高（提取风险点）。D3 已列为最高风险手法。
- 建议：提取时保持写序逐条等价（characterization 测试已锁定返回结构）。

### F2-4 `_last_model_used` 为实例属性，跨 run 泄漏模型信息
- 锚点：R0 `self._last_model_used = None`
- 现象：`_last_model_used` 是实例属性（非 attempt 局部），用于 model_changed 日志
  留痕；跨 run 共享。虽非 `_AttemptState` 候选（D3 明确仅局部量入状态对象），
  但实例属性在多 run 并发/串行下有交叉污染可能。
- 影响：低。仅日志留痕用途。
- 建议：观察项，保留（日志用途可接受）。

### F2-5 循环后 `error` 变量可能为 None（首轮即 break 的场景）
- 锚点：R9 `f"All {max_retries} attempts failed. Last error: {error}"`
- 现象：若 for 循环在某 attempt 内 `break`（cancel/artifact-gate 预算耗尽）且
  `error` 从未赋值（理论首 attempt 即 cancel 前 error 已赋；artifact-gate 分支
  均赋 error），f-string 会渲染 `None`。
- 影响：低。实测各 break 路径前均赋 `error`。
- 建议：观察项，非 bug（防御式默认值可在后续 spec 评估）。

### F2-6 R5/R6 共享 `backoff` 变量，两处各自计算
- 锚点：R5 `backoff = transient_budget[transient_retries]` / R6 同类
- 现象：两处 except 分支各自计算 backoff，无共享辅助；提取时若合并须保证
  计算顺序与预算读取一致。
- 影响：中（提取风险点）。
- 建议：提取为 `_backoff_for_retry` 辅助（等价搬移，不改变预算语义）。

## P3. 测试

### F3-1 `test_characterization_long_functions.py` 锁定的行为依赖 mock 语义
- 锚点：本变更新增 characterization 测试
- 现象：pipeline 侧测试依赖 `patch("importlib.reload")` + FakeEngine；
  runner 侧测试依赖 `_spec_is_frozen`/`_cancel_is_requested` mock。
  D4 的「函数内 import 保留」若被破坏，FakeEngine patch 将失效——本测试
  即回归哨兵。
- 影响：高（回归防护价值）。
- 建议：保留为长期回归门。

### F3-2 `AgentRunResult.run_id` 在 frozen 早退用基础 run_id 而非 attempt_run_id
- 锚点：R1 frozen 分支 `AgentRunResult(run_id, ...)` vs 其它分支 `attempt_run_id`
- 现象：frozen 早退返回 `run_id`（基础），cancel/chain_exhausted 返回
  `attempt_run_id`；观测侧按 base 匹配（注释已说明），但 run_id 字段值不一致
  是既有行为（characterization 测试已锁定）。
- 影响：低。注释明确「读侧按 base 匹配」。
- 建议：观察项，不改（锁定为当前行为）。

## 处置声明

以上疑点均**只记录不修**（design Non-Goal）。`_AttemptState` 提取时
F2-3/F2-6 为风险点，须按 D3 逐字段等价搬移；F1-3 按 D2 保留循环体。

---

## 最终态（Task 6.3，重构收口后）

本变更收口时逐项复核，全部疑点**维持只记录不修**，无一项在本变更内修复：

| 疑点 | 重构后状态 | 复核结论 |
|---|---|---|
| F1-1（`_verify_modules` 硬编码） | 保留原位（模块级 reload 清单未动） | 维持记录，后续 spec 评估 |
| F1-2（reload 静默降级 warning） | 保留（fail-open 是刻意行为） | 维持记录 |
| F1-3（472 行循环体） | 按 D2 保留循环体内（B2/B3 未拆） | 已按 D2 边界落地，不构成新增风险 |
| F1-4（双入口检查冗余） | 保留（语义已区分） | 维持记录 |
| F2-1（frozen 早退不登记收割） | 保留（frozen 在 attempt 顶部检查） | 维持记录，观察项 |
| F2-2（cancel repair 车道 keep 语义） | 保留（`_attempt_top_guards` 原样搬移） | 维持记录 |
| F2-3（`chain_cursor` 三块写点） | 经 `_AttemptState` 字段映射（R2/R7 写序不变） | **已按 D3 等价搬移落地**；characterization 返回结构锁定通过 |
| F2-4（`_last_model_used` 实例属性泄漏） | 保留（仅日志留痕） | 维持记录 |
| F2-5（error 可能为 None） | 保留（各 break 路径前均赋 error） | 维持记录 |
| F2-6（R5/R6 共享 backoff 两处计算） | 两处已分别提取为 `_maybe_in_place_retry` / `_handle_artifact_gate_retry`，各自原样保序计算 | **已随 R5/R6 提取落地**；预算读取语义逐条等价。原「提取为 `_backoff_for_retry` 辅助」建议未采纳——合并会改变预算读取时序，等价性收益小于风险，维持两处独立 |
| F3-1（characterization 测试为回归门） | 保留为长期回归门 | **已落地**：`tests/test_characterization_long_functions.py` 全部通过（重构后 75 用例） |
| F3-2（frozen 早退 run_id 用 base） | 保留（`_attempt_top_guards` 原样搬移） | 维持记录 |

**新发现（重构过程中发现并处理，非顺手修 bug）：**

| 疑点 | 处置 |
|---|---|
| WIP 提交遗留：`except Exception` 段原地退避重试块缩进错位（超出 `if (is_transient...)` 两层）致 runner.py 无法编译 | 修复：按 D2 提取 `_maybe_in_place_retry` 并修正缩进（Task 5.1） |
| WIP 提交遗留：`_record_4xx_or_transient` 提取后 switch 冷却逻辑失去原 `else:` 分支门控（4xx/无 provider 时不应触发 switch） | 修复：方法返回 `may_switch` 第三值，调用者仅在原 else 分支语义下触发（Task 5.1，维持既有熔断语义、链指针不动） |

以上两处均属**未提交现场损坏**的修复（还原设计 D1/D2/D7 既定口径），非新引入的行为变更。
