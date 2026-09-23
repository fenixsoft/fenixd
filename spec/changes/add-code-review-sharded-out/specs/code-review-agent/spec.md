# code-review-agent 规格（分片产物契约扩展）

## MODIFIED Requirements

### Requirement: 审查产物落盘契约（主产物 + 分片直写）

code-review run 的审查结果 SHALL 以「主产物 + 子代理分片」双轨落盘：主 agent 汇总写主产物 `{out_path}`（`.fenix/code-review/out-<run_id>.jsonl`），并行子代理 MUST 各自直写自己的分片 `.fenix/code-review/out-<run_id>-b<N>.jsonl`（`N` 为批次序号）。落盘义务 SHALL 为「谁审谁写、审完即写」，MUST NOT 依赖主 agent 最后统一汇总作为唯一落盘路径。

- 分片命名 MUST 为 `out-<run_id>-b<N>.jsonl`（`N` 为正整数）；其余路径形态 MUST NOT 被 ingest/进度/硬门任何一侧消费。
- 每个分片行的 JSON 结构 MUST 与主产物行完全一致（逐文件一行，`findings` 为列表，空 findings 行也 MUST 落）。
- 主 agent MUST NOT 亲自重复审查已派发给子代理的文件；收到子代理分片已落盘的批次 MUST NOT 再重写该批行（重复文件行以先落盘行为准，读侧按 `file` 去重）。
- 收到 `Async agent launched` 类元数据后，主 agent MUST NOT 以「等待批次完成通知」为由结束 run——非交互模式下 turn 结束即进程退出，异步结果不可回收；主 agent MUST 要么轮询分片文件落盘进度并同步推进自己的未派发批次，要么不派子代理全自行逐文件审查。

#### Scenario: 子代理分片直写被进度与台账双侧消费

- **WHEN** 子代理批次 3 审完 17 个文件并直写 `out-<run_id>-b3.jsonl`（17 行），主产物尚未创建
- **THEN** `read_progress` 的 `done` MUST 为 17（聚合分片），收尾 ingest MUST 把该分片全部行落账进台账

#### Scenario: 主产物与分片重复行去重

- **WHEN** 同一文件既出现在分片 `out-<run_id>-b1.jsonl` 又被主 agent 写入主产物 `out-<run_id>.jsonl`
- **THEN** ingest MUST 按 `file` 维度去重，该文件在台账 MUST NOT 产生重复条目或重复计数

#### Scenario: 主 agent 禁止以等待通知为由收工

- **WHEN** 主 agent 派发了 N 个 async 子代理并收到全部 launched 元数据，且无未派发文件可审
- **THEN** 主 agent MUST 持续轮询分片文件直至聚合行数覆盖 manifest 或批次失败可判定，MUST NOT 直接输出收工词结束 run
- **AND** run 结束时若聚合产物零有效行，产物硬门 MUST 判整轮失败

### Requirement: 产物硬门聚合口径

`repo-code-review-gate` SHALL 按聚合口径判定：主产物与全部分片的有效结果行合计为零（或文件全部缺失）才判整轮失败；任一来源存在至少一行有效结果行即通过存在性校验（manifest 覆盖率校验口径不变）。

#### Scenario: 仅分片存在时硬门放行

- **WHEN** run 收工，主产物 `out-<run_id>.jsonl` 不存在，但存在分片 `out-<run_id>-b1.jsonl`（含有效行）与 `out-<run_id>-b2.jsonl`（含有效行）
- **THEN** 产物硬门 MUST NOT 判失败，ingest MUST 消费两份分片

#### Scenario: 主产物与分片全缺失仍判失败

- **WHEN** run 收工（退出码 0），主产物与全部分片均不存在或零有效行
- **THEN** 产物硬门 MUST 判整轮失败（`repo-code-review-gate`），`error` 说明聚合产物缺失
