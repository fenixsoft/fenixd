<!-- knowledge: capability=verifier-checkpoint-resume rev=1 sources=spec/archive/2026-09-02-improve-agent-config-and-verify-resume -->

# 验证断点续跑

verifier 重验时从已完成场景之后继续，不重复消耗已通过场景。

## 现行规则

- 断点注入：构造 verifier 提示词（`_build_prompt` verifier 分支）时检查 `.fenix/verify-progress/<spec>.json`——文件存在、JSON 合法且 `done` 为该 SPEC 验证会话的累积已进度（>0）时，向提示词注入断点信息：`total`（场景总数）、`done`（已完成场景数）、`current`（上次进行中的场景描述）。
- 收到断点的 verifier 从 `done+1` 的场景继续执行：跳过已完成场景，场景总数保持 `total` 不变，每完成一个场景将 `done` 递增 1 并更新 `current`，直至全部完成。
- 无断点（`.fenix/verify-progress/<spec>.json` 不存在或 `done` 为 0）时不注入断点信息，verifier 按既有流程从第 1 个场景开始完整验证。
- 损坏安全降级：断点文件存在但内容不是合法 JSON 或缺少 `done`/`total` 字段时，视作无断点——不注入、不报错、verifier 全新开始验证，并移除或忽略损坏内容以免污染后续 attempt。
- 进度文件起点语义：沿用到断点的 verifier 首次写入进度时以断点值为起点（`done=<断点值>`）而非重置为 0，之后按场景逐一递增；全部场景完成后写入 `done=total` 与最终结果（验证结果正常写入 `.fenix-run-result.json`）。
- 写入互斥与单调性：进度文件同一时刻仅由一个运行中的 verifier 写入；不同 attempt 之间对同一 SPEC 的 `done` 值单调不减。

## 溯源

- 史前复原 — 迁移期已存在的基线：verifier 支持断点续跑，重验从已完成场景之后继续，不重复消耗已通过场景
- 2026-09-02 improve-agent-config-and-verify-resume — 机制化断点注入、损坏安全降级与进度文件起点/单调语义
