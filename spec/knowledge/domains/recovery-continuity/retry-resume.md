<!-- knowledge: capability=retry-resume rev=1 sources=spec/archive/2026-09-02-fix-fenix-token-waste -->

# 失败重试续跑

implementer 失败重试时复用同一 worktree 与同一 claude session 从失败处续跑，避免每次 attempt 从头全量重跑烧 token。

## 现行规则

- 首次 attempt 创建新 worktree 并启动新 session；后续 attempt 在同一 worktree 内以 `claude --resume <session_id>` 接续原 session，从失败处续跑而非从头全量重跑。
- 续跑不可行（如原 session 已因超时清理丢失）时记录 WARNING，回退为全新 worktree + 新 session 运行。
- run_id 每次 attempt 独立：同一 spec 的每次 attempt 生成带 attempt 序号的独立 run_id（如 `impl-<spec>-<ts>-a2`），产物文件与尝试一一对应，不同 attempt 的产物写入不同 jsonl，不混装同一文件。

## 溯源

- [2026-09-02 fix-fenix-token-waste](spec/archive/2026-09-02-fix-fenix-token-waste/) — 新增失败重试的 worktree/session 复用续跑与按 attempt 独立 run_id 的产物隔离
