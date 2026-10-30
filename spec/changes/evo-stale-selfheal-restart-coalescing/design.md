# 设计：陈旧自愈跨批次合流窗

## 落点与状态

- 判定入口：fenixd.py `_maybe_stale_selfheal_tick`（:2330，主循环 1s 粒度）。检测本身沿用 `_update_stale_code_state`（30s 重算）不动。
- 合流状态：复用 `_stale_idle_since`（空闲计时）隔壁新增「同悬置周期已按基础闸重启」标志与「合流期边沿计数」，从内存状态维护；悬置消化（磁盘 mtime 不再超 baseline）即复位。重启事实以 restart_history.jsonl 既有记录为准做幂等校验，防重启间隙状态丢失后误升闸。

## 参数

- coalesce_idle_seconds 缺省 1800s：10-18 窗批间隔 20-28 分钟，1800s 恰覆盖单批间隔上限；同时远小于 4h 强转与既有 1800s 冷却滑窗，不产生新的循环风险。
- 基础闸 idle_confirm_seconds（600s）与其项目级覆盖（config.py:2239 模式）不动；coalesce_idle_seconds 同样支持项目级覆盖。
- 影响权衡：修复生效延迟最坏从 10 分钟升至 30 分钟，但仅作用于「同周期第二次起的边沿」；首批仍 10 分钟生效，限制影响面。

## 与既有机制交互

- 4h 悬空强转：优先级最高，合流闸不得拦截（强转是防陈旧永不生效的兜底）。
- 防循环冷却（config.py:2140-2144，fenixd.py:2504-2527）：语义不变，合流等待期间不发生重启故不计次；一旦执行重启照常计次，合流不是冷却豁免。
- preflight 请求通道（core/code_stale_flag.py request_restart）：旁路合流闸——该通道语义是关键路径（收尾提交/蒸馏派发/admin choice）即时生效，被合流闸延迟会破坏 evo-add-key-path-stale-code-preflight 的目标（小时级→分钟级）。
- drain 在飞保护：不动（fenixd.py:5622-5697）。

## 观测

- 合流等待日志行：每次合流期内检出的边沿记「stale coalesce: 第 N 次边沿等待，闸值 Xs」（info 级）；执行重启时记合流收敛结果（本周期共 N 次边沿、合并为 1 次重启）。
- 不新增终态 run_metrics 字段（重启属 daemon 面，与 run 记账解耦）。

## 风险

- 框架自研单批场景（批间隔 >1800s）不受影响；批间隔 <600s 的密集场景仍由既有 600s 收编窗处理。
- 状态在 daemon 意外退出时丢失：以 restart_history 最近自愈重启时刻做幂等推导，避免重启后合流状态错乱。