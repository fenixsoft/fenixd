# 提案：修复 fast-track `implemented` 死态恢复缺口与 stale 自愈误杀在飞 OCR 车道

## Why

2026-09-23 01:46，SPEC `add-code-fix-item-level-progress`（fast-track）实现已 merge 回主树
（f19a252e）、内部验证 6/6 通过、verdict verified 已产出，仅剩 OCR 车道 join + verified→done
收尾，却卡死 `implemented` 状态 6.5 小时无任何推进。取证闭环出**两个复合缺口**，任一不修
同类事故必然复发：

**缺口一（触发侧）：stale 自愈空闲判定不识在飞 OCR 车道，重启杀 2 分钟龄 run。**
- 通宵 code-fix 批持续合码 → daemon 代码恒被判陈旧；
- `fenixd.py:1042 _is_idle()` 四维在飞信号（`pm_engine._active_runs` / 评审车道
  `_review_lane_busy` / `agent_runner._running_agents` / admin 池）**全都不含 OCR 车道**：
  车道由 `queue.py:2352 _start_impl_ocr_lane` 以裸后台线程跑维护型 run
  （`agent_runner.run_impl_ocr`），仅在 dispatcher 本地 `_ocr_lane_inflight` 字典登记
  （用于单飞去重），不进任何在飞注册表；
- 时间线实证：车道 17:44:34 UTC 启动，`_stale_idle_since` 同秒起累计，17:46:35 达 120s
  阈值触发 `陈旧自愈触发` → touch restart_request → supervisor SIGTERM 杀掉在飞车道 run
  `impl-ocr-add-code-fix-item-level-progress-1790099074`。
- 这是 2026-09-21「stale 自愈杀在飞 run」事故（评审 run 形态，已修）的 OCR 车道变体复发。

**缺口二（恢复侧）：fast-track `implemented` 是死态，join 门禁的幂等补启兜底不可达。**
- daemon 重启后启动恢复把 `testing` 回滚 `implemented`（"Recovered from interrupted
  state: testing"），event-bus 每 30 分钟重发 `spec_implemented`；
- 但 `core/pm_engine/engine.py:1288 _on_spec_implemented` 对 fast-track **有意短路**
  （防孤儿 planner 竞态，fast-track 不设 verifier 车道）——该短路对正常收尾流程正确，
  对恢复形态却是死路；
- fast-track 从 `implemented` 走到 `testing` 的唯一代码路径在 run 收尾流程
  （`fast_track.py:447 _fast_track_advance_to_verified`），中断后永不重入；
- `queue.py:2631 _ocr_join_gate` 明明有「产物缺失 → 幂等补启车道 + 停等」的恢复兜底
  （注释明确写了覆盖「daemon 重启恢复」形态），但它只在 full-mode
  `pipeline._apply_verified` 与 fast-track 收尾两处被调用——fast-track 卡
  `implemented` 时两条路都不可达。full 模式无此问题（恢复 → 入队 verifier →
  `_apply_verified` → join 门禁幂等补启，闭环完整）。
- 日志指纹：每 30 分钟一条 `Recovery: re-triggering verify` + `Handling event:
  spec_implemented`，之后无任何派发动作，无限空转。

## What Changes

- **Cap 1（fast-track 恢复出口）**：`_on_spec_implemented` 对 fast-track 的短路增加
  恢复形态放行——「分支已 merge 回主树 + 无存活实现/车道 run」的 fast-track
  `implemented` spec 不再静默丢弃，改为重入收尾推进（implemented → testing →
  OCR join 门禁 → verified → done），复用既有幂等机制，不与在飞收尾竞态。
- **Cap 2（自愈在飞豁免）**：OCR 车道在飞状态纳入 stale 自愈 `_is_idle()` 判定——
  车道启动时在 daemon 进程内可见的在飞注册表（`_ocr_lane_inflight` 升提为
  `_is_idle` 可读，或车道派发登记进 `agent_runner._running_agents`，设计定夺），
  使车道在飞期间自愈不触发重启。

## Capabilities

### 1. fast-track-implemented-recovery（modify）

fast-track spec 停留 `implemented` 且无存活 run 时的恢复出口：
事件恢复循环不再对 fast-track 一刀切短路，恢复形态重入 join 门禁驱动的收尾推进。

### 2. selfheal-ocr-lane-awareness（modify）

stale 自愈空闲判定纳入在飞 OCR 车道：车道运行期间 `_is_idle()` 返回非空闲，
自愈不重启、不杀在飞车道 run。

## Impact

- 代码：`core/pm_engine/engine.py`（`_on_spec_implemented` 恢复放行分支）、
  `core/pm_engine/dispatch/fast_track.py` 或 `queue.py`（恢复收尾重入入口，设计定夺）、
  `fenixd.py`（`_is_idle` 空闲信号集合）、`core/pm_engine/dispatch/queue.py`
  （车道在飞状态暴露，若采用注册表方案则改 `core/agent_runner/maintenance_runs.py`）
- 不改变：正常 fast-track 收尾流程时序、OCR join 门禁裁决语义（pass/defer/reject
  三档）、supervisor 优雅重启协议、`_on_spec_implemented` 对**非恢复形态**
  fast-track 的既有短路行为（孤儿 planner 防线保持）
- 风险：恢复重入与在飞收尾的并发窗口（须有「无存活 run」判据护住）；回归面含
  fast-track 正常流、full 模式恢复流、自愈冷却/自触发机制
