# 设计：fast-track `implemented` 死态恢复出口 + stale 自愈 OCR 车道在飞豁免

## Context

2026-09-23 取证闭环（add-code-fix-item-level-progress 卡死 6.5h 事故）：

- **触发侧**：`fenixd.py:1042 _is_idle()` 四维在飞信号（`pm_engine._active_runs` /
  `_review_lane_busy` / `agent_runner._running_agents` / admin 池）均不含 OCR 车道——
  车道由 `queue.py:2352 _start_impl_ocr_lane` 以裸 `threading.Thread` 跑维护型 run
  `agent_runner.run_impl_ocr`，仅在 dispatcher 本地 `_ocr_lane_inflight` 字典登记
  （单飞去重用）。车道启动当秒空闲计时开始累计，120s 后自愈 touch restart_request，
  supervisor SIGTERM 杀掉在飞车道 run。
- **恢复侧**：重启恢复把 `testing` 回滚 `implemented` 后，event-bus 周期重发的
  `spec_implemented` 被 `engine.py:1288 _on_spec_implemented` 的 fast-track 短路吞掉
  （防孤儿 planner 竞态的既有防线）；`_ocr_join_gate` 的「产物缺失 → 幂等补启车道 +
  停等」兜底只在 full-mode `pipeline._apply_verified` 与 fast-track 收尾
  （`fast_track.py:447 _fast_track_advance_to_verified`）两处被调用，卡
  `implemented` 时均不可达。

约束：正常 fast-track 收尾流（run 上下文内 implemented→testing→join→verified 连跳）
的时序与语义**不得改变**；孤儿 planner 防线对非恢复形态必须保持；supervisor 优雅重启
协议不变。

## Goals / Non-Goals

**Goals**
1. fast-track spec 停留 `implemented` 且无存活 run 时，事件恢复循环能重入收尾推进，
   走到 verified→done（含 OCR join 门禁完整裁决）。
2. OCR 车道在飞期间 `_is_idle()` 判非空闲，自愈不重启。
3. 恢复路径可观测（INFO 级日志），与在飞收尾竞态安全。

**Non-Goals**
- 不改 OCR join 门禁的 pass/defer/reject 裁决语义与修复轮上限（4.5）逻辑。
- 不改 orphaned_state 探针语义（「车道跑着不误报孤儿」与「自愈别杀车道」是两条链）。
- 不改 full 模式恢复路径（已闭环，无缺口）。
- 不引入车道子进程级监控（线程级在飞判定足够——车道有硬超时，不会永久悬挂）。

## Decisions

### D1 恢复形态判据：短路前置三条件（Cap 1）

`_on_spec_implemented` 的 fast-track 分支改为：短路**之前**先判恢复形态，三条件同时
成立才放行恢复重入，否则维持既有短路（debug 日志）：

1. `status == "implemented"` 且 `implementer_run` 非空（收尾流已过 merge 点）；
2. 实现者 run 流转录文件 mtime 超过宽限窗（复用 orphaned_state 探针的
   `ORPHANED_RUN_GRACE_SECONDS` 常量语义，取证：车道/实现者 run 心跳持续刷新转录
   mtime，活着则 mtime 新鲜）→ run 已死；
3. dispatcher `_ocr_lane_inflight` 无本 spec 在飞车道 → 收尾重入不与车道竞态。

正常收尾流不受影响：连跳在同一 run 上下文毫秒级完成，事件重发周期 30 分钟，窗口
天然错开；三条件把「事件先到、run 还活着」的竞态挡在门外。

### D2 恢复重入动作：抽取 advance 后半段复用（Cap 1）

`fast_track.py` 新增 `_resume_fast_track_after_restart(spec_name)`：

- transition `implemented → testing`（`channel="auto"`，`trigger_run_id=implementer_run`）；
- 随后执行与 `_fast_track_advance_to_verified` 后半段相同序列：`_ocr_join_gate` →
  pass 则 transition `verified` + 清零点 update + `_on_spec_verified`；defer 则停等
  （车道完成回调 `_on_impl_ocr_lane_finished` 既有唤醒路径接手——回调要求
  `status == "testing"`，重入后恰好满足，闭环）；reject 已在门禁内处理。
- 实现方式：把 advance 方法的「testing 之后」段抽取为私有方法供两处调用，**禁止
  复制粘贴状态推进序列**（清零点字段集漂移即事故）。
- 重入路径**不读** fast-track 结果文件（早已消费）：验证结论以 tasks 勾选 + 已 merge
  事实为准；verified→done 门禁 `_task_completion_blocker` 读 per-spec impl-result
  快照（merge 成功时点已落盘）。

### D3 在飞豁免：`ocr_lane_busy()` 第五维（Cap 2）

照 `_review_lane_busy` 先例（`fenixd.py:1042 _is_idle` 维度②完全同构）：

- pm_engine（或其 dispatcher）新增公开方法 `ocr_lane_busy() -> bool`：读
  `_ocr_lane_inflight` 任一为真即 busy；异常按 busy 处理（宁紧勿松，与
  `_is_idle` 既有异常策略一致）。
- `_is_idle()` 增加第五维：`self.pm_engine.ocr_lane_busy()` 为真 → 非空闲。
- **不采用**登记 `agent_runner._running_agents` 的方案：该注册表值为 Popen，车道是
  线程体跑维护型 run，语义不合；也不跨层直读 dispatcher 私有字典——公开方法封装。

### D4 观测

- 恢复放行时 INFO 日志：spec 名、三条件判据结果、重入动作；defer 时依赖既有
  join 门禁日志；不再静默。
- `_is_idle` OCR 维度命中时不新增日志（自愈阻断原因边沿日志机制既有，挂进
  `reason` 体系即可——如需区分可扩 `reason="ocr-lane"`）。

## Risks

| 风险 | 缓解 |
|------|------|
| 恢复形态误判（run 其实活着）→ 双重推进 | D1 三条件 + 转录 mtime 宽限窗 + 车道单飞去重 + transition 幂等（同状态转移安全）四层防护 |
| 恢复重入时代码/清零点漂移 | D2 强制抽取复用，禁止复制粘贴 |
| 车道线程泄漏导致自愈永久抑制 | `_ocr_lane_inflight` 在线程 finally 中清理（既有）；车道有硬超时，不会无限占用；stale 告警持续可见 |
| 自触发循环加剧（重启后又 stale） | 既有 self_triggered 窗口 + 冷却机制不动，Cap 2 只是减少无谓重启诱因 |

## 验证要点（供 specs/tasks 展开取证锚点）

- fast-track 正常收尾流回归：不触发恢复重入（三条件不成立）。
- 死态注入：implemented + run 流 mtime 过期 + 无车道在飞 → 重入 → testing →
  join defer（产物缺失幂等补启）→ 车道完成回调 → verified → done。
- 自愈：`_ocr_lane_inflight` 非空 + 代码 stale + 其余空闲 → 120s 不触发 restart_request。
- full 模式与既有孤儿 planner 防线回归不受影响。
