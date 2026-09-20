# Proposal: fix-agent-lane-efficiency

## Why

对 `.fenix/runs/archive/` 下 29 份实现/评审/规划 run 转录（合计 $524.6）做事件级取证后，除模型吞吐外确认**四类工程侧浪费**：

1. **子代理模型解析无兜底 → 并行探测原语全灭**：`Explore` 子代理 24 次派发**全部** `model_not_found`（HTTP 404，`model sent: claude-opus-4-8`）失败，跨 4 个 run。根因是直连 provider 时宿主环境仍带 cc-switch 的 `ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-4-8[1M]`，而 provider 隔离 `settings.json` 刻意**不复制** `env`（含本可救场的 `CLAUDE_CODE_SUBAGENT_MODEL`），模型解析无任何回退。直接损失约 $79，隐性后果是模型失去唯一并行探测原语、退回串行 grep。
2. **串行单工具调用 + 重复/超大文件读取**：主 run 每助手消息平均仅 **1.14–1.92** 个工具调用（503 次调用对 391 条消息）；重复 Read 159 次、重复 Edit 176 次、重复 Bash 179 次；**28%** 的 tool_result 字节来自 >20KB 的整文件 Read（单条最大 107KB）。
3. **长车道的上下文成本为 O(轮数²)**（已实测定案）：以最贵的 `spec-review` run（$72.9 / 197 轮）分解——固定脚手架 **17.4K/turn**（空会话实测，与 skills/plugins 无关，为 claude CLI 内建）+ 对话累积回放（末轮 82.5K，线性增长），合计 197 轮 ≈ **12.2M input**（校验：3.4M + 8.1M ≈ 实测 12.16M）。即 **28% 来自每轮重复的脚手架，72% 来自对话前缀被逐轮重放**。该 run 的 160 次 Bash 中 **63 次是 OCR 超时复现探针**，是对话累积的主要来源。
   **前缀缓存不可依赖（探针定案）**：直连各 provider 实测——`cache_control` 显式写入后，同一前缀第二次调用 `cache_read` 仅 113（`inferaiapi.com`）或恒 0（`maomaoai`/`bigmodel.cn`/`deepseek`），即**网关不产生可复用命中**；且全部 provider 一致，非某一家的问题。因此「靠缓存摊薄上下文」这条路不通，唯一一阶杠杆是**压轮数与压每轮增量**。
4. **600s Bash 超时陷阱 + 提示词自相矛盾**：`_result_gate_section` 要求「无后台节拍、MUST 用前台有界入口」，但 Bash 工具本身有 600s 硬上限会把长任务强制转后台，模型遂陷入 `sleep → echo RUNNING` 轮询。全库 10 次 600s 工具超时，约 **100 分钟纯墙钟浪费**；`impl-fix-spec-review-blocking-dispatch-…-a1` 单 run 墙钟 254 分钟而 API 仅 44 分钟。

## What Changes

- **子代理模型解析兜底（点1）**：provider 隔离 `settings.json` 注入该 provider 可用的子代理模型（`CLAUDE_CODE_SUBAGENT_MODEL` 及 tier 兜底），使内建子代理走 provider 自身模型而非 cc-switch 官方名；子代理启动失败落显式告警而非静默吞掉。新增配置键（含 Dashboard 设置页 UI，配置键与 UI 同步铁律）。
- **工具调用效率与轮数治理（点2 + 点3 主杠杆）**：
  - **批量并行**：同一轮内相互独立、无数据依赖的工具调用 MUST 合并为一次批次提交；
  - **定向读取**：优先 `Grep` / 带范围 `Read`；MUST NOT 反复整文件读取未变更大文件；同 run 内已读且未变更的文件 MUST NOT 重复读取；
  - **取证深度上限（降低轮数，一阶杠杆）**：评审/实现车道的取证 MUST 以「最小可判反证」为限，MUST NOT 为完整复现 SPEC 的每条断言而穷尽探测——评审职责是判 `blocking` vs `repairable`，不是重跑实现方的全部验证；
  - **输出裁剪**：探针/命令输出 MUST 裁剪（`head -c` / 取关键行 / 落临时文件只回读关键片段），MUST NOT 把数十 KB 原始输出整块进对话。
- **上下文经济性可观测（点3 观测面）**：run 末落逐 run **轮数 / 上下文峰值 / input / cache_read** 指标并在 `context_cost_per_turn` 超阈值时打诊断告警（O(N²) 结构可见化，防回归）；提供可复现探针 `bin/probe_prompt_cache.py` 重新验证网关缓存能力（结论可能随网关升级变化）。缓存探针结论落文档，**明确「不做缓存优化」**——避免后续重复投入。
- **长任务前台有界等待契约（点4）**：对齐 600s 工具上限与「前台有界入口」要求——长任务统一走**在 600s 内必然返回的分段入口**或**一次后台启动 + 完成通知等待**，消除 `sleep → echo RUNNING` 自旋；修正提示词中「MUST NOT 后台 + 轮询」与实际工具能力的矛盾。

## Capabilities

### New Capabilities

- `subagent-model-availability`: 子代理（`Explore`/`general-purpose`/`Plan`）在直连 provider 车道下的模型解析兜底与失败可见化。
- `agent-tool-call-efficiency`: 长车道的工具调用效率契约——批量并行、定向读取、同 run 去重、取证深度上限、输出裁剪。
- `agent-run-token-economy`: run 级上下文经济性可观测（轮数/上下文峰值/input/cache_read 指标与阈值告警）与网关前缀缓存能力的可复现探针（含「不可依赖缓存」的定案记录）。
- `long-task-foreground-wait`: 超长任务在 600s 工具上限下的前台有界等待契约。

### Modified Capabilities

- `agent-prompt-files`: 契约段集合扩展（效率段、取证深度段、长任务等待段），并约束各段注入位置不破坏既有顺序断言。
- `agent-run-artifacts`: run 转录新增逐 run 上下文经济性指标字段（读侧扩展，不改变流式处理行为）。

## Impact

- **代码**：
  - `core/agent_runner/runner.py`：`_build_isolated_settings` 注入子代理模型键；`_run_claude` 流式循环读侧累计轮数/上下文峰值/token 指标；子代理失败告警。
  - `core/agent_runner/prompt_builder.py`：新增「工具调用效率」「取证深度」「长任务前台有界等待」段（按 agent_type 注入）；修正既有 `_result_gate_section` 中与工具能力矛盾的措辞。
  - `core/config.py` + Dashboard 设置页（`settings_routes.py` + 前端）：新增子代理模型配置键。
  - `bin/probe_prompt_cache.py`（新）：网关缓存能力探针。
  - `bin/run_full_suite.py`（既有有界入口）：确认/对齐 600s 内分段返回语义。
- **API**：无外部 API 变更；Dashboard 新增一个配置项（子代理模型）。
- **配置**：新增 config 键（子代理模型覆盖），需 Dashboard 设置页承载。
- **测试**：新增子代理模型注入测试、上下文经济性指标解析测试、探针测试、提示词段注入与顺序断言测试；既有 `test_agent_runner_*` 为护栏。
- **运行时**：改 `runner.py` / `prompt_builder.py` / `config.py`，daemon 需重启生效（`restart_request` 信号，由 supervisor 消费）。
