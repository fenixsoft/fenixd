# design: split-self-review-stderr-noise-count

## Context

- 噪声形态实测：18 个 run 档案（/root/potplayer-base/.fenix/runs/archive）中 17 个各含 1 条 `type='stderr'` 事件，文本字节级一致 `[claude-code:unrecognized_model] {"model":"glm-5.3-flash","query_source":"sdk"}`，全部在第 5 行启动段；深扫 `_scan_run_midflight`（core/self_review.py:864-941）从第 1 行扫起，故启动段定噪被计入「中途stderr」。
- 既有降噪格局：白名单常量 `CLI_STDERR_NOISE_TEXT_PATTERNS`（provider_circuit.py:101-103）+ 判别入口 `is_cli_stderr_noise`（:227-239）已存在；深扫 first_stderr 已跳噪声（self_review.py:915-925，reduce-cli-stderr-noise-attribution D2）；knowledge_backfill 失败归因已滤噪（knowledge_backfill.py:651-668，D3）；runner error 拼装已降噪（runner.py:5640-5656，D5）。
- 缺口与约束：`stderr_count` 保留全量是已验收 SPEC `spec/changes/evo-reduce-cli-stderr-noise-attribution/specs/cli-stderr-noise-filtering/spec.md` 的明文 SHALL（「stderr 计数 SHALL 保留全量（含噪声行）」），本 spec 以 ADDED Requirement 细化其口径，不回写该 SPEC 文本。`stderr_count` 消费点仅 self_review.py:1471 渲染与 tests/test_self_review_midflight.py:265/285/299/313/326/348/392 断言（:348/:392 夹具 stderr 均为真实行、新口径下计数值不变），另有 :511 渲染形态断言（同 `_stall_transcript` 夹具、「中途stderr=2」值不变），爆炸半径可控。

## Goals

- 「中途stderr=」恢复信息量：0 = 真无 stderr，≥1 = 至少一条真实诊断行。
- 保留定噪可见性（注记），不丢失「取证现场完整」的原始意图。
- 判别单源不动、分类零扰动、原始留证零改动。

## Decisions

- **D1 分离计数而非直接丢数**：`stderr_count` 改非噪声口径 + 新增 `stderr_noise_count`。直接把噪声行丢弃会让「真实拒模型诊断行（同前缀形态）」也被吞掉计数；分离后两路信息都在，渲染层再合成注记。
- **D2 判别单源复用**：self_review 局部导入 `is_cli_stderr_noise`（沿用既有 :882 延迟导入形态），不在本模块复制 pattern。pattern 行首锚定于告警类别标签而非模型名，模型名变化（glm→其他）不破坏匹配；新噪声形态按 provider_circuit.py:92-94 的设计追加 pattern 即可。
- **D3 渲染注记承载可见性**：`_collect_midflight_section`（self_review.py:1462-1478）行拼装改为非噪声计数 + 尾注「（另 N 条已知 CLI 启动噪声）」，等价承接原「保留全量」的观测意图，且让「全噪声」与「无 stderr」在摘要上可区分。
- **D4 不动三处**：first_stderr 语义（既有 D2 验收行为）、runner 原始 stderr 落盘与 `exc.stderr_lines` 原始信号通道（瞬断判定依赖，provider_circuit.py:129-131 亦明文禁止裸 stderr 判据）、provider_circuit 分类常量。源端抑制（provider_marker/CLI 参数）不可行：provider_marker 是框架私有 jsonl 事件（provider_circuit.py:704-744），CLI 不可见。

## Risks

- **真实拒模型诊断被剔出 stderr_count**：同前缀形态的真诊断行不再计入主计数——死因证据仍经 error/result 事件（first_error）与原始 stderr 双通道到达，分类行为不变；`stderr_noise_count` 与 first_error 并读可复原现场。
- **与未归档既有 change 的协调**：`spec/changes/evo-reduce-cli-stderr-noise-attribution/` 尚在 changes 目录（2026-09-27 已完成待归档）；本 spec 为独立新 change，不触碰其文件，落盘/归档顺序无耦合。但两者对 `stderr_count` 的 SHALL 语义相抵（旧「保留全量」vs 本 spec「只计非噪声」）——本仓 spec 体系为逐 change 冻结快照、无统一合并步，冲突以文字消解：本 spec「深扫 stderr 计数噪声分离」Requirement 明文声明取代旧 SHALL 的计数条款（first_stderr 降噪与全噪声置空语义不受影响），归档后以该 supersession 声明为准，未来回读旧档不得据其回退计数口径。
- **渲染形态漂移**：注记文案变化可能影响下游对深扫行的文本匹配——深扫行仅经 daily_summary 进入每日摘要 prompt（core/agent_runner/maintenance_runs.py:557 注入），无机器消费点（grep 全仓无其他读点），风险限于可读性。