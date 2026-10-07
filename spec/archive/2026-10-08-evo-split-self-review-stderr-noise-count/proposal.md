# proposal: split-self-review-stderr-noise-count

## Why

claude CLI 对非 Anthropic 模型名每 run 恒打 1 条启动期 stderr 诊断（`[claude-code:unrecognized_model] {"model":"glm-5.3-flash","query_source":"sdk"}`，实测 17 个 run 档案字节级一致、全在第 5 行）。自省深扫的 `stderr_count` 按既有 SPEC `evo-reduce-cli-stderr-noise-attribution`（2026-09-27 验收）决意保留全量计数，导致凡 glm/deepseek 链离群 run 的深扫行恒报「中途stderr=1」——2026-10-03 自省窗口唯一一条 stderr 深扫命中即此定噪（potplayer-base `.fenix/todo.md:71` 引数据摘要第 6 节），持续稀释「中途信号」节的证据可信度。first_stderr 已滤噪（降噪语义不动），缺口仅在计数口径。

## What Changes

- 深扫 `_scan_run_midflight` 的 stderr 分支把噪声行从 `stderr_count` 剥离：`stderr_count` 只计非噪声行，新增 `stderr_noise_count` 单独计数（判别复用 `is_cli_stderr_noise` 单源）。
- 深扫行渲染（`_collect_midflight_section`）以非噪声计数为准，噪声 >0 时追加「（另 N 条已知 CLI 启动噪声）」注记——承接原「保留全量」的取证可见性意图，信息不丢失、信号不再恒真。
- first_stderr 既有语义（跳过噪声行、全噪声置空）零改动；runner 原始 stderr 事件落盘与 provider_circuit 瞬断/切换分类判据零改动。

## Capabilities

- self-review-midflight-signals（新增 Requirement，细化既有「深扫 first_stderr 降噪」Requirement 的计数口径）

## Impact

- 代码：`core/self_review.py`（扫描 + 渲染）、`tests/test_self_review_midflight.py`（口径断言更新 + 新用例）。
- 兼容：`_scan_run_midflight` 返回 dict 增键不改旧键；消费端仅本模块渲染（:1471）与测试断言。
- 不影响：admin 告警、error 归因（runner `_denoise_stderr` D5 已降噪）、瞬断分类（用原始 stderr）。