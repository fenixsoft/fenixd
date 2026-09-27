# ADR-078：悬空 run 终态补写清扫（启动 + 运行期双兜底）

date: 2026-09-14
status: accepted

## Context

run 终态只能由 run 线程（或 daemon 侧转写）写出，监督机制（轮询环 + deadline）是 in-process 的：宿主死亡即失效。daemon 非优雅死亡（SIGKILL/OOM/断电）后 jsonl 永久悬空——统计失真、孤儿 claude 持锁阻断重派。排水路径先写 interrupted 标记的方案不成立：排水语义是等自然收工，先写会污染正常完成路径，且 SIGKILL 场景 daemon 根本没有执行机会。仅靠启动期清扫时，daemon 存活期间的非优雅死亡仍悬空至下次重启（实测 12.3h）。

## Decision

- 补写统一口径：对判定悬空的 run 以 O_APPEND 原子追加 `{"type": "interrupted", "reason": "<startup|runtime> terminal-state sweep", ...}`——不销毁可恢复数据，只把「框架已知的死亡」显式化；STATE 级状态回迁不做，由既有 recovery/full_scan 消费补写后的事实。
- 启动清扫：新 daemon 启动早期（AgentRunner 初始化后、任何派发前）扫全部尾部无终态事件的 jsonl 补写——启动时注册表为空 + 单实例锁，存量无终态 run 必为遗留死 run；孤儿 claude 进程存活不阻塞（写者是 daemon，孤儿不再写文件）。
- 运行期清扫三重判据（AND，缺一不扫）：① run_id 不在在飞注册表（权威源）② mtime 停更 ≥ 阈值（1800s，模块常量不进配置）③ 尾部无终态事件。驱动挂 event_bus 周期扫描循环（full_scan 前），零新增接线参数。
- 安全性依据：result 终态只能由 run 线程 finally 写出，线程不在注册表 = 写入者已死；派发瞬间与 finally 内 pop-后-写 的窗口因 mtime 新鲜被自然跳过。
- run 线程级缺口源头修复：轮询环 `except Exception` 兜底写 error 行（异常归因落盘为文件末行）后原样 re-raise，保持 attempt 预算/STATE 语义不变；清扫器退居进程级死亡的唯一兜底。

## Consequences

- 悬空检测延迟上界 ≈ 阈值 + 扫描周期（约 60min），对比事故 12.3h。
- 补写刷新 mtime 会短暂污染裸 mtime 读侧（排序/门禁），由流式读窗口自愈；清扫器不改写读者侧。
- 注册表内卡死线程是同盲区（无法区分卡死与慢），与监督 deadline 一致，接受。
