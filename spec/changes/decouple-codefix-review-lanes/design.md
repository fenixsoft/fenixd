# 设计：decouple-codefix-review-lanes

## Context

- 事故时间线（09-24，UTC+8）：14:20 周期审查 run 启动（内含 ocr scan）；15:15 code-fix 延迟批合回成功后**无任何派发**；16:42 人工取消审查 run（僵死 2h20m/49s CPU）+ 陈旧自愈触发 daemon 重启；16:45 code-fix 立即恢复派批。
- 根因候选 A（取证重点）：延迟批合回走 defer 消费者路径，可能未执行 `_resubmit()` 自驱动推进；链的下一次激活依赖「审查收尾 inserted>0」事件或周期扫描——僵死 run 永不收尾、扫描间隔 30min 且该窗口内扫描未拾取 → 90min 空窗。
- 根因候选 B：存在显式「审查在飞则 code-fix 不派发」门控（待 grep 取证排除）。
- 既有设施：run 级 stalls 统计（`agent_runner` 逐 run 输出 stalls>60s）、进度产物 mtime、`mergeback_wip_overlap` 式告警分级、cancel_run + 急救落账路径（`_read_code_review_out` + upsert）。

## Goals / Non-Goals

**Goals:**
- code-fix 吞吐与审查 run 健康度解耦
- 僵死审查 run 有界时间内被自动收走（不再依赖人工取消 + 重启）

**Non-Goals:**
- 不治理审查车道内部的重试/降级策略（todo.md 已登记，独立治理）
- 不做审查 run 的部分恢复（急救路径沿用既有落账能力）
- 不改 code-fix 批内部的回归锁语义

## Decisions

- **D1 取证先行并留证**：任务 1 为只读取证（grep 门控 + 复核 09-24 空窗），结论写进实现分支的 `docs/` 或代码注释；候选 A/B 定案决定解耦改动落点（A → 补 `_resubmit` 等价推进；B → 移除门控）。两个候选的修复不互斥，按取证结果落地。
- **D2 看门狗双判据**（mtime AND CPU 同时无进展）：单 mtime 判据会被「网络僵死但进程活着空转」欺骗（本次事故 CPU 49s/2h20m 恰为双判据价值实证）；单 CPU 判据会误杀长 IO 等待的正常 run。阈值 `admin.review_stall_minutes` 缺省 30（对齐 admin monitor 周期量级），检查频率随 admin monitor。
- **D3 取消后走既有急救**：cancel → `_read_code_review_out` 产物抢救入账 → 告警（复用既有 cancel/salvage 链路），MUST NOT 新造落账路径。
- **D4 解耦边界**：只解除「审查在飞 → code-fix 停」的逻辑耦合；两者共用的回归主机锁、worktree 主机资源保持自然竞争（物理冲突点不假装解耦）。

## Risks / Trade-offs

- [看门狗阈值过短误杀慢但健康的审查 run] → 双判据 + 30min 缺省 + 任一判据有进展即重置；误杀代价=急救落账后下轮重审（有台账幂等）
- [解耦后台账并发写加剧] → 台账写入已有 `jsonl.lock` 单写者约束；任务中含并发写回归验证
- [defer 批补自驱动推进改变链节奏] → 推进语义与常规批对齐（本就是 spec 既定语义，属修 bug 非改设计）

## Migration Plan

取证任务零风险先行；解耦与看门狗随分支合入生效，配置键缺省即启用。回滚 = revert + 配置阈值调大（看门狗部分可独立回退）。
