# code-fix 车道与周期审查 run 的调度解耦（decouple-codefix-review-lanes）

本文是 SPEC `decouple-codefix-review-lanes` 的取证定案与交付说明：2026-09-24 周期审查
run 网络僵死（2h20m 仅 49s CPU）期间 code-fix 车道 90 分钟未派批的事故机制、
「批派发与审查在飞状态解耦」的语义边界、以及审查 run stall 看门狗的使用与调参。

## 1. 事故时间线（2026-09-24，日志为 UTC，括号为 UTC+8）

| 时刻 | 事件（`~fenix/logs/fenixd.log` 原文摘要） |
| --- | --- |
| 06:17:08（14:17） | 周期审查 run `code-review-1790230628` 启动（manifest 101 文件，review_kind=scheduled） |
| 06:24–06:28（14:24–14:28） | code-fix 第 2 批（run `code-fix-1790230559`）修复完成，合回被主树未提交改动挡住（重叠 `CodeFixProgressCard.tsx`）→ wip_gate_blocked，批入延迟台账保留现场 |
| 06:15→08:15（14:15→16:15） | full scan 每 30 分钟照常完成（`Full scan complete: handled=314`，06:15 / 06:45 / 07:15 / 07:45 / 08:15 五轮），每轮末尾都触发 code-fix `checkpoint()` |
| 07:15:51（15:15） | 07:15:20 那轮 full scan 的 checkpoint 内，延迟批经 `_process_deferred_merges` 合回成功：`code-fix 延迟批合回成功：核销 4/4 条（branch=fenix/code-review-fix-1790230556）`；同一 checkpoint 因 `total_open==0` 收敛 idle——**此刻台账已无 open 条目可派** |
| 06:22→08:42（14:22→16:42） | 审查 run 在 ocr scan 阶段网络僵死：2h20m 仅 49s CPU（0.5%），run 永不收尾 |
| 08:42:07（16:42） | 人工写取消信号：`cancel_run` 登记旗标 → 轮询环 0.25s 内 terminate 子进程；取消理由确认「审查产物 101/101 文件已完整落盘」。收尾抢救读数 `inserted=0, updated=0`（in-process 抢救未把产物转化为台账条目） |
| 08:44:19（16:44） | daemon 重启（Periodic scanner started） |
| 08:44:42（16:44） | 滞留在 `out-code-review-1790230628.jsonl` 的 45 条 findings 才入账（`first_seen_at` 全部为该时刻，review_id 仍为原 run） |
| 08:45:10（16:45） | code-fix 立即恢复派批（`agent_env 注入` → run `code-fix-1790239510`） |

台账侧旁证（`items.jsonl` 的 `first_seen_at` 直方图，UTC）：06-24 当日 T05=4 条
（延迟批那 4 条），T06/T07=0 条，T08=45 条（取消+重启后入账的那批）——**07:15 到
08:42 的「空窗」里台账确实没有任何 open 条目**。

## 2. 取证定案

### 候选 A：defer 批合回路径缺自驱动推进 `_resubmit` —— 原形态排除

代码证据（`core/code_fix.py`）：

- 批收尾 defer 路径：`_defer_merge_back` 返回 `"consumed"` → `_run_batch` 收口
  `if outcome in ("success", "consumed"): self._resubmit()`——延迟批保留现场后链
  **立即**自驱动投递下一批（延迟条目经 `_deferred_item_ids` 排除出可选池，收敛性
  不破坏）。
- 延迟台账重试路径：`_process_deferred_merges` 挂在 `checkpoint()` 内
  （already_running 守卫之后、选批/收敛早退之前），合回成功核销后**同一个
  checkpoint 继续走选批→投递**，不需要等下一次外部节拍。

事故日志也印证：07:15:20 full scan → 07:15:51 延迟批合回成功，同链完成、无推进缺失。

### 候选 B：显式「审查在飞则 code-fix 不派发」门控 —— 排除

代码证据：`CodeFixOrchestrator.checkpoint` 的完整守卫链为 `enabled`（/链上授权旗标）
→ `already_running`（code-fix **自身**单飞，只扫 `code-fix-` 前缀 run）
→ `no_open_items` → `wip_overlap_at_select` → 回归契约 fail-closed。全链**没有任何
一处**读取审查 run 的在飞状态；两路激活（审查收尾 inserted>0、`event_bus`
full-scan 末尾）也都是无条件调用 `checkpoint()`。审查在飞对 code-fix 只有物理资源
竞争（回归主机级套件锁、worktree 主机资源），由既有锁自然串行，无逻辑互斥。

### 真实机制定案

90 分钟空窗不是「派发被门控挡住」，而是三件事叠加：

1. **落账与链激活都绑死在审查 run 收尾事件上**：findings 增量写在
   `out-<run_id>.jsonl`，但 `upsert_findings` 入台账发生在 `run_code_review` 收尾；
   `inserted>0` 才激活 code-fix 检查点。僵死 run 永不收尾 → 45 条 findings 滞留
   产物文件 → 台账零 open → code-fix 的周期 checkpoint 每轮如实判定
   `no_open_items` 空转（这一段 code-fix 行为正确）。
2. **僵死 run 无自动收走机制**：既有 `code_review_stall` 告警只做「人工判断是否
   取消」的提示（done==0 判据还覆盖不了「审查本体已完成、卡在收尾阶段 scan」的
   形态），不取消、不落账、不释放车道——占道时长无上界，直到人工取消 + 重启。
3. in-process 抢救在该次未转化（收尾抢救读数 inserted=0），产物转正滞后到重启后。

对应治理：Requirement 1（解耦）确保「有 open 条目时审查在飞不挡派批」结构性成立
并用测试钉住；Requirement 2（看门狗）给僵死 run 一个有界收走路径——取消即触发
run 收尾，既有急救落账路径随之执行，台账及时转正。

## 3. 解耦语义（Requirement 1 落地说明）

- code-fix 批派发/链推进的判据集合里**没有**「审查 run 在飞」；本 SPEC 以回归测试
  钉住该不变量（`tests/test_codefix_review_decoupling.py`）：
  - 审查 run 在飞（构造 running=true 的审查进度产物）+ 台账有 open 条目 →
    `checkpoint()` 照常投递批（4.1）；
  - defer 批合回成功 → 同一 checkpoint 继续推进下一批 / 批收尾 defer 返回
    `consumed` 自驱动 `_resubmit`（4.2）；
  - 审查正常收尾 `inserted>0` → 两路激活语义不变（4.4）。
- 候选 B 无门控可移除；本节即排除证据记录。
- 物理冲突点（回归主机级套件锁、worktree 主机资源）保持自然竞争，不假装解耦。

## 4. 审查 run stall 看门狗（Requirement 2 使用说明）

### 语义

admin monitor 每轮巡检（`run_once`，与 `_check_code_review_stall` 同挂载点）检查
在飞审查 run：

- **双判据**（同时无进展才计时）：
  1. 进度产物 mtime：`out-<run_id>.jsonl` 与全部分片 `out-<run_id>-b<N>.jsonl` 的
     最新 mtime（经 `code_review.shard_paths` 统一口径取分片集合）；
  2. 进程 CPU 时间：run 子进程进程树的累计 CPU 时间（utime+stime，含存活子进程，
     `core/agent_runner/maintenance_runs.agent_process_cpu_seconds`）。
- **任一判据有进展即重置计时**（mtime 变化或 CPU 增长都算进展）；双判据同时无进展
  持续达阈值 → 触发。
- 阈值 `admin.review_stall_minutes`，缺省 30（对齐 admin monitor 巡检周期量级）；
  缺失/非法/非正整数一律回退 30，巡检不因脏配置中断。
- CPU 判据不可解析（run 子进程句柄缺失等）时按 fail-open 不触发——看门狗宁可漏杀
  不可误杀，且没有进程句柄时 `cancel_run` 也无从终止。

### 触发动作

1. `runner.cancel_run(run_id, reason=..., by="review_stall_watchdog")`——复用既有
   run 粒度取消原语（登记旗标 → 属主轮询环 terminate→grace→kill → cancelled 终态行）；
2. run 收尾后**既有**急救落账路径自动执行（`run_code_review` error 收场抢救：
   聚合读产物 → upsert 入账；不触发 code-fix 检查点的既有红线保持不变）；
3. AdminStore 告警留痕（`review_stall_watchdog`，kind=ESCALATION，单 run 去重键
   `review-stall-watchdog-<run_id>`），evidence 携带双判据冻结值与已停滞时长。

MUST NOT 新造落账路径（design D3）；看门狗只做「取消 + 告警」，产物转正走既有链路。

### 调参

- `.fenix/config.template.yaml` 的 `admin.review_stall_minutes`（分钟，正整数）。
- 调小（如 15）：僵死收走更快，但慢 IO/长网络等待的正常审查 run 被误杀概率上升；
  双判据下「进程活着但网络僵死空转」形态（本次事故）在 CPU 判据上表现为零增长，
  15 分钟也可安全判死——按本仓审查 run 的常规时长分布自行权衡。
- 调大（如 60）：接近零误杀，但僵死占道上界随之放大。

### 误杀处置

- 误杀代价 = 急救落账后下轮重审：台账 upsert 按指纹幂等（已入账条目只刷新
  last_seen），已完整落盘的产物不会丢；被误杀 run 以 `review_stall_watchdog` 告警
  与 run jsonl 的 `cancelled` 终态行（reason 含 `review_stall_watchdog`）留痕。
- 判别是否误杀：对照告警 evidence 里的 `mtime=<值>` 与产物文件实际 mtime、
  `cpu_seconds=<值>` 与进程实际耗时——若判据读数与事实不符（如 mtime 刚刷新但读数
  陈旧），先怀疑巡检频率/文件系统 mtime 粒度，再调大阈值。
- 确属误杀且希望立即重审：项目页「代码审查」分面手动触发一次审查即可，无需要
  回滚看门狗。
