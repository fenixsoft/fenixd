# 设计：add-codefix-batch-parallel

## Context（现状与约束）

- code-fix 批执行结构：`run_code_fix`（maintenance_runs.py）单次 `_run_claude` 在批 worktree 内跑一个 agent；agent 按 file 分组串行修复、逐组落 out 行、一次提交；批 worker 随后回归（主机级锁）→ 合回 → 核销。
- 批实测：agent 段 94–166 轮（~15–30 min，瘦身 4a245470 后 94 轮基线）；回归 ~4.5 min（6012 用例）。
- 子代理并行先例：code-review 车道 manual_full 实测 orchestrator 分 14 批派子代理（Task 工具一条消息多调用=真并发），子代理按批写结构化产物——模式已被验证，教训是「中转产物不落 out_path 导致进度 0%」（12963f5d 已修的纪律）。
- 轮次/时间上限已解除（e1f1a57f `max_turns=None`；`agents.timeout_overrides` 两车道 604800s），并行带来的轮次增长无天花板风险。
- 网关长尾实测：api_retry 31 次/1262 事件——并发放大请求量会放大限流，并发度必须保守。
- 条级进度读侧：`read_fix_out(worktree, run_id)` 实时读 out 行合成 `item_done/current_item`——只要 out 行随组增量落盘，进度卡即实时。

## Goals / Non-Goals

**Goals**
1. 批内多文件组时 agent 段耗时 ÷ 2–3（并行子代理），out 行随组增量落盘（进度可见）。
2. 框架契约零改动：单 run / 单 out_path / 单 commit / 一次回归一次合回。
3. 子代理失败可兜底（orchestrator 重做），单组批退化为串行。

**Non-Goals**
- 批间并行（多 worktree 多批；回归主机锁与合回串行化钳制，属 pipeline-throughput SPEC）。
- 并行度配置化/前端化（常量 3，先收基线）。
- 子代理各自跑测试（验证仍汇总后一次执行——子代理跑测试会产生并发测试冲突与资源争用）。

## Decisions（决策）

### D1 并行放在 agent 侧（提示词协议），不放框架侧
框架侧并行（run_code_fix 派 N 个 _run_claude）需要 N 条 run 流、N 份 provider 注入、事件落盘与汇总机制——改造面大且与单 run 契约冲突。agent 侧 Task 子代理（一条 assistant 消息多个 tool_use=真并发）由 CLI 原生承载，框架视角仍是「一个 run」，契约零改动。审查车道已验证该模式成熟。

### D2 分组规则沿用既有 file 分组，组间文件互斥
现提示词已按 `file` 分组（瘦身 4a245470）；并行协议直接以组为子代理粒度。同一条目的 file 唯一 → 组间无编辑交集；跨组共享文件（如公共导入）与串行现状风险一致，不新增处理。

### D3 并发波次 ≤3，固定常量写进提示词
- 网关限流放大风险（api_retry 实证）；
- 并行度收益递减（agent 段 ÷3 后回归占比回升）；
- 配置化触发「新增配置键必须带 Dashboard UI」规则，先以常量收基线，调优证据齐后再议配置化。
波次语义：同时至多 3 个子代理在飞，完成一组回收一组、补派下一组。

### D4 out 落盘责任在 orchestrator（单写者）
子代理返回结构化结果（每条目一行 out 记录 + 改动已落 worktree），orchestrator 校验行格式（item_id/status）后**立即**追加写 `{out_path}`。单写者消除并发写文件冲突，也保证条级进度合成（读侧）看到的是已裁决集合。子代理 MUST NOT 自行写 `{out_path}`。

### D5 子代理失败三级兜底
① 子代理无响应/报错 → orchestrator 亲自重做该组（串行路径）；② 重做仍失败 → 该组条目按既有 skipped 语义标注（unfixable/needs_human）；③ 产物行格式非法（缺 item_id/status）→ 该条按未处置处理并重试一次。任何兜底不阻塞其他组。

### D6 验证与提交仍是「一次」
全部组落盘后：按触碰面一次定向验证（既有验证段规则）→ 单次 commit（信息列全批 item_id）。子代理 MUST NOT 自行验证/提交（防并发测试冲突与提交撕裂）。

### D7 单组退化与噪声批
批仅 1 个文件组或条目 ≤2 → 不派子代理（调度开销>收益），orchestrator 直接按串行路径处置。判定写入提示词作为硬规则。

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| 子代理并发改动隐式冲突（共享导入/常量文件被多组同时编辑） | 分组按 file 粒度互斥；跨组共享文件场景与串行现状等价；验证一次兜底 |
| 并发放大网关限流（api_retry 变多） | 波次 ≤3 保守上限；子代理失败有 D5 兜底 |
| 子代理产物缺 title/file 等字段 → 落行非法 | orchestrator 落盘前校验必填键；非法行按 D5③ 重试 |
| 忽略标记（fenix-ignore）在并行下重复添加 | 标记规则随组 prompt 下发（组内文件互斥 → 无跨组重复）|
| 轮次消耗上升（编排轮次） | 上限已解除（max_turns=None）；编排轮次 ≈ 组数/波次，远小于节省的处置轮次 |
| 批退化路径回归（单组/双条目批行为漂移） | D7 硬规则 + Scenario 锁定 |

## Migration / 兼容

- 提示词每次派发现读 → 合回后下一批即生效，无需重启；串行路径（单组/小批）逐字保留。
- 框架侧（code_fix.py / maintenance_runs.py）零改动——回归风险集中在提示词语义，由 Scenario 1–5 锁定。
- 效果基线：瘦身批 94 轮/~30min agent 段；并行后预期 agent 段 ~12–15min（3 并发），对比口径见 [[fenixd-codefix-prompt-slim-baseline]]。
