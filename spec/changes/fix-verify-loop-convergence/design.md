## Context

### 事实（2026-09-21 事故，均已回源码复核）

**事故形态**：`add-freeze-stop-inflight-agents` 验证轮连续 3 轮失败场景集逐字相同
（`fail_history.json` round2/round3 `failed_scenarios` = `["web-freeze-inflight-stopped-hint"]`），
judge 每轮判 `product-bug`，框架每轮重派 implementer，最终 judge 重跑 6/5 熔断冻结。
产品代码经同实例 Playwright 复现证明**正确**。

**框架已有的零件（全部核实存在，但都停在「提示」档）**：

| 零件 | 位置 | 现状用途 |
|---|---|---|
| `repeat` 判定 | `core/pm_engine/family.py:370` `_classify_fail_history` | 仅 `_format_fail_history_evidence`（`:410`）拼告警文案 |
| 零变更哨 | `core/pm_engine/verification/branch_guard.py:117` `_implementer_zero_change` | 判「零 commit 且零 Edit/Write」；**只看绝对值，不看声明路径** |
| 投机门禁 | `core/pm_engine/verification/escalation.py:996` `_speculative_bug_found_gate` | 全部驱动场景 speculative 才抑制；**有截图即 evidence-backed** |
| 改道门 | `core/pm_engine/verification/escalation.py:557` `_scenario_defect_reroute_gate` | 要求 `product-bug==0` |
| 同因重派熔断 | `core/pm_engine/dispatch/queue.py:1520` | **作用域显式排除** bug-found 路径 |
| 三条硬上限 | `judge_gate.py:75` / `family.py:524` / `budget.py` | 各自独立冻结，error 不含诊断 |

**门禁插入点**：`_apply_bug_found`（`pipeline.py:747`）——`_speculative_bug_found_gate`
（`:759`）与 `_scenario_defect_reroute_gate`（`:776`）之间的既有 5 道守卫链。

**重验范式**（复用投机门禁的预算结构，`escalation.py:1045-1100`）：`update_spec(status=
"implemented", tester_run=None)` + 计数器 + `enqueue(spec_name, "verifier")`；预算耗尽 → blocked
+ `escalation_notifier`。

**诊断数据可得性**：`fail_history.json` 每轮 `{round, cause_type, failed_scenarios,
failure_class, run_id}`（`infra_classify.py:288`）；声明路径经 `extract_declared_entries`
（`core/deliverables.py:346`）可得。

## Goals / Non-Goals

**Goals**
- 同一失败场景集连续 N 轮 + 零实质变更 → **停止重派实现者**，转验证复核（清缓存重验一次），
  预算耗尽才冻结转人工。
- 「实质变更」按 `## Deliverables` 声明路径度量，勾选 tasks.md 不算进展。
- 缓存命中 `product-bug` 且零实质变更 → 不得直接驱动打回。
- 三条硬上限冻结时 error / 告警带 `repeat` + 零变更诊断。
- Administrator run 失败有独立降级（直接人工告警），不静默死。

**Non-Goals**
- 不改 judge 判据与 `VERDICT_CLASSES` 四类枚举（不新增第五类——见 D2 理由）。
- 不改验证真机取证链（本 SPEC 不引入产物指纹比对，只做「识别无进展 → 停止重派」）。
- 不改真·产品缺陷路径（`repeat` 未达阈值或存在实质变更时行为逐字不变）。

## Decisions

### D1 无进展判据 = `repeat` 连续性 + 实质变更（双判据，缺一不放行）

新增门函数 `_verify_loop_convergence_gate(pipeline, spec_name) -> bool`（放 `escalation.py`，
与 `_speculative_bug_found_gate` 同族），在 `_apply_bug_found` 内 `_speculative_bug_found_gate`
**之前**调用（先判循环，再判证据强度）。

判据（**纯机械、零 token**）：

```
repeat_streak = 尾部连续 repeat 轮数（_classify_fail_history 已有 repeat 判定）
substantive   = 本轮实现者分支相对上一轮，在本 SPEC `## Deliverables` 声明路径上是否有 diff
触发          = repeat_streak >= N  AND  substantive == False
```

N 取 `verify_engine.loop_convergence_repeat_threshold`（缺省 2，见 D6）。

**理由**：单看 `repeat` 会误伤「真·难修缺陷（同一场景连修两轮仍未过）」——那种情况每轮都有实质
代码变更。加上「零实质变更」判据后，触发条件精确收敛到「实现者已无杠杆、框架仍在重派」。

### D2 不新增第 5 类 classification（关键取舍）

考虑过给 `VERDICT_CLASSES` 加第五类「不可复现/证据冲突」。**否决**，理由：

1. 该枚举是 judge 的**产出契约**（`verdict_check.py:34`），贯穿报告校验、分布统计、改道门、
   抑制门——加一类牵动全链，风险高。
2. 本 SPEC 的目标是「**停止无效重派**」，不是「给失败定性」。无进展闸门达成同一目的且判据纯
   机械（不依赖 LLM 判断「是否不可复现」——那个判断本身可能出错）。

**未来线索（不在本 SPEC 范围）**：若日后出现「真机与取证不符」的复现实证，再单独立项「证据冲突
分类 + 验证产物指纹比对」。

### D3 实质变更判定：声明路径受限 diff

新增 `_implementer_substantive_change(pipeline, spec_name, result) -> bool`（放 `branch_guard.py`，
与 `_implementer_zero_change` 并列）：

- 取本 SPEC `## Deliverables` 声明路径集（复用 `extract_declared_entries`，`deliverables.py:346`）；
- 对实现者分支（`result.branch`）做**路径受限** diff：只统计声明路径上的改动；
- 声明路径全无 diff（含 `tasks.md` / `.fenix-run-result.json` 等元数据被排除）→ `False`（无实质变更）；
- 声明段缺失 / 提取失败 / git 失败 → **fail-open 返回 `True`**（保守按「有变更」处理，不触发闸门——
  与零变更哨 fail-open 同向）。

**理由**：现状 `_implementer_zero_change` 只看「零 commit 且零 Edit/Write」，实现者每轮勾 tasks.md +
写结果文件即绕过。这是本次循环的直接逃逸口。

### D4 缓存降级：命中 product-bug 且零实质变更 → 不驱动打回

`tag_cached_attributions`（`verdict_check.py:987`）现状仅按「无截图」降级 speculative。新增：
缓存命中 `product-bug` **且** 本轮 `_implementer_substantive_change == False` 时，把该场景的
`attribution_level` 降级为 `speculative`（复用既有降级机制，不新增字段语义），从而被既有
`_speculative_bug_found_gate` 吸收。

**理由**：跨轮缓存把上轮结论固化；本场景每轮重生成截图 → 一直 `evidence-backed` → 投机门禁永不
抑制。「有截图」≠「截图可信」。

### D5 硬上限诊断贯通 + 升级通道失败降级

1. **诊断贯通**（三处上限冻结写 error + 告警 evidence）：
   - `judge_gate.py:75` `_judge_hard_cap_freeze`
   - `family.py:524` 升级闸门（已有 `_format_fail_history_evidence`，补 `repeat`/零变更结论）
   - `budget.py` 实现预算耗尽冻结
   error 文案形如：`…（诊断：连续 N 轮同失败集且实现分支零实质变更——疑似验证假失败循环，非缺修复）`。

2. **升级通道失败降级**：`maintenance_runs.py:256` Administrator run 失败（异常/CLI 退出）后，
   现状只 `logger.warning`。新增：失败且 signal 属「可自动处置失败」时，落一条**直接人工告警**
   （`escalation_notifier`，signal_type 复用既有 `admin_dispatch_failed` 或等价），使唯一破局通道
   失败时至少留下人工可见的升级，不静默。

### D6 配置键（MUST 带 Dashboard 界面）

新增 `verify_engine.loop_convergence_repeat_threshold`（正整数，缺省 2）。**按「新增配置项必须带
Dashboard 界面」约定**，须在设置页「验证」页签暴露（与既有 `verify_engine.*` 同区），并在
`.fenix/config.template.yaml` 增注释条目。若实现者判断该键更适合直接复用既有
`verify_engine.credibility_gate_max_retries` 语义而不新增键，MUST 在 design 修正说明并在结果文件
登记理由——**但「复核预算」与「repeat 阈值」是两个语义，默认新增独立键**。

### D7 复核动作 = 清裁决缓存 + 重验一次

闸门触发时（首次）：清本 SPEC 的 `verdict_cache.json`（复用 `save_verdict_cache` 写空表）→
`update_spec(status="implemented", tester_run=None)` + `_loop_gate_attempts` 计数 → `enqueue(verifier)`。
预算（`verify_engine.loop_convergence_max_retries`，缺省 1）耗尽仍触发 → blocked + 人工升级。

**理由**：清缓存掐断「上轮结论固化」；重验让真机重新取证一次。不做强制 rebuild（那是 D2 未来线索
的范畴），先做最小可用闭环。

## Risks / Trade-offs

- **风险**：把「真·难修缺陷」误判为循环（若实现者的修复恰好不在声明路径上）。**缓解**：fail-open
  设计——声明段缺失/提取失败一律判「有变更」放行；且 `repeat` 阈值缺省 2（需连续两轮同失败集）。
- **风险**：`_apply_bug_found` 守卫链增一门，影响「真 bug-found」路径。**缓解**：门只在
  `repeat>=N 且零实质变更` 时返回 True；用例锁定「有实质变更 → 门返回 False → 原路径不变」。
- **取舍**：不做验证产物指纹比对 → 「取证与真机不符」的根因未被直接消灭，只被「停止重派 + 重验
  一次」缓解。若重验后仍是同一假失败，最终仍会 blocked 转人工——但**成本从 $76 降到 1-2 轮**。
  这是有意的分期：先止血，再深挖。