# 提案：知识蒸馏批次持久化与崩溃续跑（knowledge-distill-resume-guard）

## Why

知识蒸馏（归档 spec 提炼知识页的管线）的批次状态是纯进程内内存态，daemon 重启即蒸发，已两次实锤造成入库断流：10-09 至 10-10 窗口内 5 批蒸馏派发零完成（.fenix/logs/fenixd.log 行 15055/15395/16817/16831/16913，最后一条「完成」停在 14107f52 即 10-09 03:31:37 +0800），3 个新知识页与 5 个 tracked 同步改动滞留主树 27.6 小时，最终靠 maintree_stray_wip_stale 巡检升级 major 告警、消耗一个 admin run（admin-fenixd-1791587146，273 秒）兜底入库（5a4e95a3）；另两批（evo-add-verify-evidence-placement-contract、evo-add-impl-wallclock-budget-sizing）零产出零台账，知识彻底丢失。

结构性缺口三处（已回源核实）：

1. 队列不落盘：core/knowledge.py:851 起 DistillManager 的 self._queues 为进程内 dict，worker 为 daemon 线程；dispatch 仅 extend 内存 list。批次进行中 daemon 死亡 → 队列与执行现场同灭，无任何持久痕迹（唯一台账 _register_todo_retry 仅在失败路径触发，且是给人看的队列不进自动消费）。
2. 自愈空闲判定盲区：fenixd.py:1544 _is_idle 五维度（pm_engine._active_runs / 评审车道 / agent_runner._running_agents / admin worker 池 / impl-ocr 车道）均不含蒸馏 worker 与其 spawn 的 claude 子进程——蒸馏在飞不阻塞 stale-code 自愈重启。两天内 3 起中断（10-09 03:19:00Z、06:20:18Z，10-10 19:40:30Z）全部发生在派发后 1-14 分钟内的陈旧自愈重启窗口，时间链一致。
3. 重启零恢复：core/knowledge.py 无任何启动扫描/恢复逻辑；dispatch 唯一调用链是归档事件（core/archive_commit.py:88-91），归档已完成后不再触发，重启后批次永久蒸发。

## What Changes

1. 批次 pending 台账落盘：DistillManager.dispatch 入队时同步写 .fenix/knowledge-distill-pending.json（tmp+os.replace 原子写，与既有 knowledge-distill.lock 同目录）；批次成功收尾（commit 落库或判定无变更）或放弃产出清理确认后移除条目；「校验通过但提交失败」的滞留路径保留条目。
2. daemon 启动恢复：FenixDaemon.initialize 末尾扫描 pending 台账，存在未完成批次即重新入队消费（实际 run 仍经 .fenix/knowledge-distill.lock flock 跨进程互斥，与 dashboard --serve 进程竞争安全），恢复条目数落日志。
3. 自愈空闲判定补蒸馏维度：fenixd.py _is_idle 新增第六维度——蒸馏 worker 线程存活或进程内队列非空时判非空闲，从源头阻止 stale-code 自愈在蒸馏在飞时重启击杀。RUN_TIMEOUT_SECONDS=1800 硬超时保证 worker 有界退出，该维度不会使空闲判定永久失效。

## Out of Scope

- 不改 maintree_stray_wip_stale 巡检升级与 commit_stray_wip 一键提交（散件治理族按设计工作，保留作最后一道兜底）。
- 不改蒸馏提示词、校验规则（validate_knowledge）与重试轮数（MAX_FIX_ROUNDS）。
- 不做跨机器/跨项目恢复，仅本项目 daemon 生命周期内的续跑。