# 提案：add-codefix-batch-parallel

## Why（为什么做）

code-fix 批内为**单 agent 串行**处置：按 file 分组顺序修复，agent 段实测 94–166 轮/批（~15–30 分钟），是批全程（37 分钟基线）的主要构成。审查车道（code-review）已验证**子代理分批并行**模式可行（14 批子代理同构先例）；code-fix 的条目天然按 file 分组、组间无编辑交集，具备同样的并行条件。

提示词瘦身（4a245470）已砍掉空转轮次（-43%），下一步提速杠杆就是批内并行：agent 段 ÷ 并行度（2–3），批全程预计 37min → 15–20min。

## What Changes（改什么）

**agent 侧并行协议（提示词改造，框架契约零改动）**：`agents/code-fix.md` 新增并行处置段——批内 ≥2 个文件组时，按组派子代理并行处置（并发波次 ≤3），orchestrator 负责汇总：

1. **分组派发**：文件组划分沿用现规则；每组一个子代理，prompt 携带该组条目 JSON + 修复契约（最小改动/标记规则/逐组 out 行格式）
2. **增量落盘**：每组子代理返回后，orchestrator **立即**把该组 out 行追加写入 `{out_path}`（条级进度实时可见；MUST NOT 攒到全部组完成）
3. **一次验证一次提交**：全部组完成后按触碰面做一次定向验证 + 单次 commit（提交与验证契约不变）
4. **失败兜底**：某组子代理失败/产物不可解析 → orchestrator 亲自重做该组；仍失败按既有 skipped 语义标注
5. **单组退化**：批只有 1 个文件组（或条目 ≤2）→ orchestrator 直接自行处置，不强派子代理
6. **并发上限 3**（提示词固定值，模块先例对齐 FAIL_RETRY_MAX 的「常量不设配置键」决策）：防网关限流放大（api_retry 已实测 31 次/千事件）

## Capabilities（能力）

- `code-fix-batch-parallel`（新增）：code-fix 批内按文件组并行处置协议。

## Impact（影响面）

- `agents/code-fix.md`：新增并行处置协议段（核心改动，提示词每次派发现读、合回即生效）。
- 框架侧零改动：单 run / 单 out_path / 单 commit / 回归+合回契约全部不变；条级进度读侧（read_fix_out 实时合成）天然兼容。
- 轮次/时间上限已解除（e1f1a57f + timeout_overrides），并行带来的轮次增长无天花板风险。
- 非目标：批间并行（多 worktree 多批，pipeline-throughput SPEC 领地）；并行度配置化（避免配置键+UI 负担，先以常量 3 收集基线）。
