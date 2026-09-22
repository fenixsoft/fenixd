# add-code-fix-item-level-progress 设计

## Context

code-fix 车道（add-code-review-auto-fix）的进度模型是批级：编排器在批启动写 `fix-progress.json`（`phase="fixing"`），批收尾才更新 `done`。fenixd 实测一批 20 条约 60 分钟，期间进度卡片恒 0%，用户无法区分工作与卡死（2026-09-22 第 1 批运行期间两次误判）。

条级进度源在契约上已存在：`agents/code-fix.md` 输出契约要求 agent 每处置完一条立即向 `<worktree>/.fenix/code-review/fix-out-<run_id>.jsonl` 追加一行 `{item_id, status: fixed|skipped, file}`；编排侧已有容错解析器 `core/code_fix.py read_fix_out()`（损坏行跳过、缺失返回空）。缺口仅在：读侧（dashboard 轮询的 `read_progress()`）不知道当前批的 `worktree`/`run_id`，无法定位该文件。

## Goals / Non-Goals

- Goals：进度卡片在批内展示条级进展（已处置 N/M 条 + 刚完成条目摘要）；全链路容错回退；零批级行为变更。
- Non-Goals：不改 agent prompt 与输出契约；不改批次划分/回归门/合回逻辑；不引入推送（WebSocket）——沿用既有 2s 轮询；不做历史批次进度回放。

## Decisions

### D1 条级进度 = 读侧实时合成，不新增写侧回写路径

进度文件 `fix-progress.json` 仍只承载批级状态。条级字段由 `read_progress()` 在读时经 `read_fix_out()` 现算——理由：

- 写侧（编排器）在批内阻塞于等待 agent run 结束，无从感知条级进度；若引入看门狗线程回写则新增并发面（进度文件读写竞态），违背「无并发引入」目标。
- out 文件是 agent 逐条追加的既有产物（append-only、单写者），读侧 stat+解析的竞态窗口天然安全（读到半行由 `read_fix_out` 的损坏行容错兜住）。
- worktree 收尾删除后读不到 out——但那时批已收尾、`fix-progress.json` 已承载终值，条级字段本来就该让位（规格 Scenario「批收尾后条级字段让位」）。

### D2 批上下文经进度文件传递（而非读侧反推）

`fix-progress.json` 新增 `worktree`/`run_id` 两键，编排器批启动时与 `phase="fixing"` 同次原子写入，批收尾清除。备选「读侧按 `.claude/worktrees/impl-code-review-fix-*` glob 反推最新 worktree」被否：glob 前缀归属歧义是本仓已知事故模式（spec 名互为前缀误归属、run 流前缀盲区两案），显式落盘消除猜测。

### D3 `current_item` 的 title/file 以注入清单补全

out 行只含 `{item_id, status, file}`，`title`/`line` 等展示字段从编排器注入本批的清单条目（批启动时已在内存/可从批次文件取）回查匹配 `item_id` 得到。清单匹配失败（清单外条目、历史脏行）时 `current_item` 降级为仅含 out 行自带的 `item_id/status/file`。

### D4 兜底语义：null 三态而非 0

「明细不可得」与「已处置 0 条」在用户感知上是两件事（后者读作卡死）。规格强制：不可得时字段为 null，前端显示「批内明细尚未产生」而非 `0/N`。

### D5 风险：out 文件落盘时序实证

设计期取证发现一疑点：fenixd 第 1 批 run 中途（21:32，agent 已完成 6/9 任务组）`<worktree>/.fenix` 目录暂不可见，而批次最终成功（产物硬门要求 out 有效行非空，说明收尾时文件在场）。可能解释包括 worktree 清理时序观察误差或目录创建时机晚于首条完成。**不阻塞本设计**（读侧对缺失场景已兜底），但 tasks 安排先用最小批次复现实证 out 文件的落盘时序与路径，若实证发现 agent 实际不遵守逐条追加契约，则以实证结果修订读侧字段口径后再落地（实现者按实证结论实现，不臆测）。

## Risks / Trade-offs

- 轮询频率 2s 下每次 `read_fix_out` 读一个小 jsonl（≤20 行）+ 清单回查——开销可忽略。
- worktree 路径属 `.claude/worktrees/`（gitignored 运行时区），进度文件记录绝对路径仅作读侧索引，不进 git。
- 旧进度文件（无新键）与旧批次在飞时升级：读侧全 null 回退，前端不显示条级文案——零迁移。

## Migration Plan

纯增量字段，无迁移。部署顺序自由（读侧对缺失键容错，写侧新键对旧读侧不可见）。

## Open Questions

- 无（D5 的实证任务在实现期闭环，实证结论不影响接口形状——只影响「逐条追加」是否如实发生，兜底路径已覆盖失约场景）。
