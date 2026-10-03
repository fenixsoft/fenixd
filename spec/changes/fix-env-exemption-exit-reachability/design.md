# 设计：fix-env-exemption-exit-reachability

## Context

2026-10-03 potplayer-base/android-station-port 事故链（judge_rerun_cap 冻结 6/5）取证结论：

- 级二握手（`escalation.py::_handle_env_exemption_handshake`）命中后走 `_handle_verdict_env_exemption_inconclusive`，自动重验至 `_inconclusive_attempts >= 3`（`verify_engine.inconclusive_max_attempts`）才写 B7 SIGNAL（`_write_inconclusive_loop_signal`，kind=SIGNAL 唤醒 Administrator）；
- 每轮重验 = verify_engine 重执行 → report.json 顶层 timestamp 翻新 → `_judge_round_state` 判定上下文换键（轮内计数清零）+ `is_verdict_stable` 失效（mtime 变化）→ judge gate 必真实派发 → `_judge_rerun_count` +1；
- `_judge_rerun_count` 生命周期累计（唯一清零点 = verified，`state_machine.py` 生命周期注释 + `verdict_evidence.py` 清零点），总预算 `_MAX_JUDGE_RERUNS = 5`；
- 该 spec 握手命中前已消耗 5/5（首轮判定 1 + 场景原地修复重判 2 + bug-found 修复轮重判 2），重验第 1 轮后的 gate 即第 6 次 → `_judge_hard_cap_freeze` 冻结；
- 轮内节流（`_JUDGE_ROUND_MAX_REAL_DISPATCHES = 2`）因 timestamp 换键全程未触发；
- `inconclusive_loop` 不在 `ADJUDICATION_CHOICES` 注册表内——SIGNAL 只走 Administrator 通道，前端告警区无 choices 下拉，人工无一键裁决入口。

## Goals / Non-Goals

**Goals**

1. env 全归类场景下，人工在**第一次**握手命中即收到带 choices 的可裁决告警（裁决及时性契约：告警自解释 + 一键处置）；
2. 瞬时环境抖动（级一）保留自愈重试，但同签名复现不空转；
3. 任何 inconclusive 重验路径不再与 judge 生命周期预算互斥——到 admin 出口永不因 `_judge_rerun_count` 触顶被截断；
4. 放行查询锚点（`latest_resolved_disposition(spec, "inconclusive_loop")`）零变更。

**Non-Goals**

- 不改握手 fail-closed 语义与 `_env_exempt_disposition_is_stale` 时效锚点；
- 不动 judge 硬上限数值（`_MAX_JUDGE_RERUNS = 5` 不变）；
- 不做环境指纹探测（失败签名一致性已是「环境是否变化」的充分代理，见 D2）。

## Decisions

### D1：级二首次命中即升级，级一保留一次自愈重试

级二命中的前提是 judge 已对全部失败作出 env 终局裁决——重验只有在环境变化时才有新信息，而框架没有任何环境变化探测器，重验是纯预算焚烧。因此级二**首次命中即升级停车**。

级一（全 blocked-env、零 fail，场景从未执行）面向的是瞬时抖动（模拟器起不来、端口占用），保留自动重验但上限 3→2，且加签名一致提前升级（D2）。

理由：两级语义不同——级二「已裁决等豁免」（缺人的决定），级一「没跑成等环境」（缺环境的恢复）。前者等人，后者等环境，等的方式不该相同。

### D2：失败签名一致性 = 「环境是否变化」的充分代理

签名字段：失败/blocked 场景 id 集 + 每场景失败签名（断言 type + 归一化 actual 摘要，归一化复用 `_normalize_fail_signature` 口径：数字→N、去引号、折叠空白）。全部一致 → 判定「环境未变化，重验必复现」→ 提前升级。任一不同 → 环境有变化信号 → 允许继续自愈重试。

数据源：`fail_history.json` 已存每轮 failed_scenarios；本轮签名在升级判定点从 report.json 场景表现算，无需新持久化（比较在内存完成，签名摘要随 SIGNAL evidence 落库供人工核对）。

### D3：预算隔离用「旗标 + 分账计数器」，不用提额

`_in_inconclusive_reverify` 旗标由握手 inconclusive 处置点置位；`_judge_dispatch_gate` 计数分流：

```
旗标置位 → bump _judge_inconclusive_dispatches（上限 = inconclusive_max_attempts）
旗标未置 → bump _judge_rerun_count（既有语义不变）
```

选分账而非「重验轮豁免计数」：独立计数器保留可观测性（重验轮到底烧了几次 judge 一目了然），且自有上限兜底防旗标泄漏导致的无限派发。

旗标清除点（防泄漏）：
- judge 申报结论非全 env（bug-found / verified 放行 / scenario-repaired）→ 清旗标恢复正计（正常路由的 judge 消耗照旧计入生命周期账）；
- verified 落定 → `_judge_inconclusive_dispatches` 清零 + 旗标清除（`verdict_evidence.py` 既有清零点扩展）；
- 人工 `reset_verification` → 清零清单追加两个新字段。

### D4：choices 复用 alert-resolve 既有闭环

`inconclusive_loop` 注册三项：`grant_env_exemption`（新动作）/ `manual_fixed_reverify`（复用 `_MANUAL_FIXED_REVERIFY` 共享常量）/ `abandon`（复用 `_ABANDON`）。新执行器 `_exec_grant_env_exemption`：经 AdminStore 写 kind=DISPOSITION（signal_type=inconclusive_loop、result 显式放行语义、note 落人工审计文本）+ 调 `reset_verification` 复用既有清计数/清验证进度逻辑。DISPOSITION created 晚于 SIGNAL，天然通过 `_env_exempt_disposition_is_stale` 时效校验——放行→重验→握手查得放行→合法 verified，全链零新机制。

人工告警走 `escalation_notifier`（`_send_human_escalation_alert` 按注册表自动附加 choices 快照），severity=major 进人工待处理队列。SIGNAL（Administrator 通道）与 ESCALATION（人工通道）双通道并存：Administrator 可自动核查环境，人工可一键豁免，二者竞争由 DISPOSITION 幂等锚点（同 spec 只认最近一条 resolved）收敛。

### D5：error 文案与冻结看门狗豁免的兼容

升级停车写 implemented + error 文案，**不用** FREEZE_ERROR_PREFIX 冻结前缀（本设计是「暂停自动重验等裁决」而非结构化冻结——人工经 choices 解锁，不走 unfreeze 通道）。`_dispatch_backoff_until` 置退避（复用 `_SCENARIO_REPAIR_REVERIFY_DELAY_SECONDS` 同款手法）防 `spec_is_undriven` 判 orphaned_state 误报成条。

## Risks / Trade-offs

- **[级二失去自愈重试]** 环境恰好自愈的 spec 少了自动恢复机会 → 概率极低（环境无人动不会自愈），且 `manual_fixed_reverify` 一键承接人工修环境后的重验；签名一致提前升级（级一）本就承认「复现=无新信息」。
- **[旗标泄漏]** 异常死亡时旗标滞留 → 下一轮 judge 结论非全 env 即清除（恢复路径全覆盖）；verified 清零点兜底；`_judge_inconclusive_dispatches` 自有上限独立兜底。
- **[双通道竞争]** Administrator 与人工同时处置 → DISPOSITION 按 `latest_resolved_disposition` 取最近一条，后到者覆盖语义可接受（留痕完整可审计）。
- **[告警噪音]** 级二首次命中即告警，比旧设计（3 轮后）告警更早 → 这正是目的（裁决及时性），且 escaping 的只是「确需人工豁免」的信号，噪音为零。

## 涉及文件（Deliverables 依据）

- `core/pm_engine/verification/escalation.py`（级一/级二升级时序 + 签名比较 + 人工告警发射）
- `core/pm_engine/verification/judge_gate.py`（gate 计数分流）
- `core/pm_engine/verification/verdict_evidence.py`（verified 清零点扩展）
- `core/state_machine.py`（字段常量 + 清零清单注释）
- `core/dashboard/data/adjudication_choices.py`（注册表注册）
- `core/dashboard/data/admin_actions.py`（grant_env_exemption 执行器）
- `tests/test_env_exemption_handshake.py` 等配套测试
