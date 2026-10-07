# spec: split-self-review-stderr-noise-count

## ADDED Requirements

### Requirement: 深扫 stderr 计数噪声分离
自省中途信号深扫（`core/self_review.py` `_scan_run_midflight`）收集 stderr 事件时，`stderr_count` SHALL 只累计非噪声行（判别复用 `core/agent_runner/provider_circuit.py` 的 `is_cli_stderr_noise`，MUST NOT 在 self_review 内复制 pattern）；噪声行计数 SHALL 单独产出为 `stderr_noise_count`；first_stderr 既有选取语义（跳过噪声行、全噪声置空）SHALL 保持不变；run 产物 jsonl 的 stderr 原始事件 SHALL 保持不过滤（取证现场完整）。本 Requirement 细化并取代既有 change `evo-reduce-cli-stderr-noise-attribution`（specs/cli-stderr-noise-filtering「深扫 first_stderr 降噪」Requirement）中「stderr 计数 SHALL 保留全量（含噪声行）」的计数条款——两文档并存时计数口径以本 Requirement 为准（first_stderr 降噪与全噪声置空语义不受该取代影响）。

#### Scenario: 混合行计数分离
- WHEN 某 run 的 stderr 事件依次为 1 条 `[claude-code:unrecognized_model]` 噪声行 + 1 条真实诊断行
- THEN `stderr_count == 1`、`stderr_noise_count == 1`
- AND `first_stderr` 取该真实诊断行（既有语义不变）

#### Scenario: 全噪声计数归零
- WHEN 某 run 的 stderr 事件全部为 `[claude-code:unrecognized_model]` 噪声行
- THEN `stderr_count == 0`、`stderr_noise_count == 噪声行数`
- AND `first_stderr` 为空（既有「全噪声置空」语义不变）

### Requirement: 深扫行渲染注记
`_collect_midflight_section` 渲染「离群 run 事件流深扫」行时，「中途stderr=」SHALL 取非噪声计数；`stderr_noise_count > 0` 时 SHALL 在同行追加「（另 N 条已知 CLI 启动噪声）」注记（N 为噪声行数）；噪声为 0 时 SHALL NOT 出现注记。

#### Scenario: 定噪不再冒充信号
- WHEN 离群 run 的 stderr 仅为 1 条已知启动噪声、无其他 stderr 行
- THEN 深扫行不出现「中途stderr=1」，而呈现「中途stderr=0（另 1 条已知 CLI 启动噪声）」
- AND 噪声存在性仍可见（取证可见性承接原「保留全量」意图）

#### Scenario: 无噪声行形态不变
- WHEN 离群 run 的 stderr 无任何噪声行（如真实诊断行若干）
- THEN 深扫行「中途stderr=N」形态与注记均与既有行为一致

### Requirement: 判别单源与分类零扰动
噪声判别 MUST 单源复用 `is_cli_stderr_noise`；本变更 MUST NOT 改动 `core/agent_runner/provider_circuit.py` 的 pattern 常量语义、瞬断/切换分类判据，MUST NOT 改动 runner stderr 原始事件落盘行为。

#### Scenario: 分类行为零回归
- WHEN 某 run 因 provider 明确拒模型而失败（stderr 含 unrecognized_model 诊断行）
- THEN 瞬断/切换分类判定仍读原始 stderr 信号（`exc.stderr_lines`），结果与本变更前一致
- AND run 产物 jsonl 中 stderr 原始事件仍完整留证