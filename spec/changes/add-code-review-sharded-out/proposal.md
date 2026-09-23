# Proposal: add-code-review-sharded-out

## Why

code-review 车道连续两晚空跑（code-review-1790178542 烧 $21.54、code-review-1790180307 烧 $17.90，均零产物）：agent 每次都选「async 子代理并行审查」策略，而 claude -p 非交互模式下 turn 结束即主进程退出，**async 子代理结果永不回收**；主 agent 等待期通读全部 manifest 文件却零落盘，`read_progress` 的 `done` 恒 0，用户在质量分面盯「审查进行中（manual_window）」0% 干等。三轮提示词修复（09-23 批次落盘纪律、09-24 单文件语义消歧 + 等待期纪律）均无法改变行为，已定性为架构问题。

## What Changes

- **分片直写**：审查 run 允许的并行子代理各自直写自己的分片产物 `out-<run_id>-b<N>.jsonl`，主 agent 汇总兜底仍写主产物 `out-<run_id>.jsonl`——落盘义务从「主 agent 最后汇总」改为「谁审谁写、写完即见」。
- **读侧聚合**：`read_progress` 的 `done`/`current` 改为聚合「主 out + 全部分片」的有效行数；`_read_code_review_out`（收尾 ingest 读侧）同样聚合分片，保证台账完整。
- **硬门聚合口径**：`_check_repo_code_review_artifact` 升级为聚合口径——主产物 + 分片合计零有效行才判失败。
- **禁 async 等待收工**：提示词明确「收到 Async launched 元数据后 MUST NOT 以等待批次通知为由收工」——非交互模式下该等待不存在，turn 结束即丢结果。
- **事中停滞告警**：run `running` 且聚合 `done==0` 持续超 15 分钟 → 发 admin alert（人工告警），让「零进度」从用户肉眼发现变为框架主动上报。

## Capabilities

### New Capabilities

- `code-review-progress-visibility`: 审查进度的聚合读侧与停滞告警——`read_progress` 聚合主产物与分片计算 `done`/`current`；`running` 且零进度超阈值时产生 admin alert。

### Modified Capabilities

- `code-review-agent`: 产物落盘契约从「单一 `{out_path}` 逐文件追加」扩展为「主产物 + 允许子代理分片 `out-<run_id>-b<N>.jsonl` 直写」；收尾 ingest 与产物硬门升级为聚合口径；新增「禁 async 等待收工」约束。

## Impact

- `core/code_review.py`（`read_progress`、产物路径工具函数）
- `core/agent_runner/maintenance_runs.py`（收尾 ingest 读侧 `_read_code_review_out` 调用点、停滞告警接线）
- `core/agent_runner/result_gate.py`（`_check_repo_code_review_artifact` 聚合口径）
- `agents/code-review.md`（落盘契约与禁等待收工条款）
- `tests/test_code_review.py`（聚合读侧与硬门口径回归）
- 不改变台账条目结构（`items.jsonl` schema 不动）；不改 dashboard 前端（`progress` 响应字段形状不变，仅取值口径变化）。
