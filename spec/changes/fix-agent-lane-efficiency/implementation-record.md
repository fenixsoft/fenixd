# Implementation Record — fix-agent-lane-efficiency

本文件登记实现阶段的关键实测结论与决策（tasks 1.2 / 1.6 / 4.2 / 5.2 要求的实现记录）。

## 1.2 生效通道实测（settings.json env vs 进程 env_overrides）

**结论：`settings.json` 的 `env` 段是确定性生效通道**（实现采用 settings.json env 注入子代理映射）。

实测方法（2026-09-20）：构造一个含 `env.ANTHROPIC_MODEL=totally-invalid-model-xyz` 的隔离
`settings.json`，以 `CLAUDE_CONFIG_DIR=/tmp/test-settings-env3 claude -p ... --verbose
--output-format stream-json` 执行，观察结果：

- stream-json 的 `system/init` 事件中 `"model":"totally-invalid-model-xyz"` —— CLI 从
  settings.json env 读到了模型名并作为实际发送模型；
- 随后 `[claude-code:unrecognized_model] {"model":"totally-invalid-model-xyz",...}` 且
  assistant 事件报 `"error":"model_not_found"` —— 模型名确实被传入 API 请求。

即 settings.json `env` 覆盖了宿主环境对子进程的模型解析（CLI 合并 settings.env 到进程 env）。
故 `_build_isolated_settings` 写入的 provider 重算 env 映射可被确定性地消费；进程
`env_overrides` 通道（runner 的 `env_overrides`）只是另一层 env 注入，且其与 settings.json
env 之间 settings.json env 优先级更高（本次实测多轮 CLI 探针未发现覆盖失效），采用
settings.json env 作为唯一注入通道、`env_overrides` 保持既有语义不变。

## 1.6 配置键命名冲突处置

`.fenix/config.yaml:17` 存在 `agents.subagent_model: claude-sonnet-5`（2026-09-02
add-agent-llm-isolation 遗留），全库无任何 Python 读点，为死键。

**决策：保留新键 `agents.subagent_model_override` 为唯一活键；`agents.subagent_model`
保持死键（不读、不写）。** 依据：

- design D1 推荐「复用 `agents.subagent_model`（兼作死键收编）」但要求二择一登记；
  实测该死键在 `.fenix/config.template.yaml` 中不存在、用户配置中可能有残留，将其
  复活为活键会让「模板无键、配置有键、代码读键」三角不一致；
- 新键 `subagent_model_override` 语义更精确（override = 覆盖 provider model），
  docstring 与 docs/help/09-config.md 均已明确二者边界：`subagent_model` 为死键、不生效。
- `ConfigLoader.get_subagent_model_override` MUST NOT 回退读取死键——两个键同时可被读作
  「子代理模型」即违反 D1「不留下两个活配置键」。

## 4.2 上下文经济性告警阈值定标

`verify.context_cost_per_turn_threshold` 缺省 **200000**（per-turn 平均 20 万 input
tokens）。

定标依据（design D3 引用的 29 份 run 分解）：最贵 spec-review run 末轮对话上下文
82.5K、脚手架 17.4K/轮，197 轮合计 ~12.16M input，per-turn 均值 ≈ 61.7K。若把
「诊断告警」定在均值（~62K）会大量误报长车道正常轮次；取缺省 200000（约 3.2× 该
run 均值）只对显著 O(N²) 膨胀的 run 告警，兼顾降噪铁律。

**最小样本门槛**：`turns < 5` 或缺 usage 的零轮空跑只落指标、不打告警（daemon 每个
agent 均经 `_run_claude`，含大量零轮空跑与维护类 run，一律告警会把诊断信号淹成噪声）。

**指标来源口径**：turns / input_tokens / cache_read_input_tokens 全部取自本 run 转录
事件（`assistant` 事件数与 `message.usage` 累计），MUST NOT 取 CLI `result.modelUsage`
（D3 记账段已实测 modelUsage 与 result.usage 相互矛盾）。`context_peak_tokens` 为估算值
（对话单次 input 峰值），估算口径：assistant 事件 usage.input_tokens 的逐轮最大值。

## 5.2 bin/run_full_suite.py --timeout 语义确认

实测结论：`--timeout <N>` 语义为「**自身在 N 秒超时内返回**」——脚本以
`subprocess.communicate(timeout=N)` 运行 pytest，超时 kill 后收集 faulthandler 栈输出并
以退出码 124 收口，不会无限等待（fix-run-hang-amplification D3 既有实现，本次未改）。
全量回归实测耗时 223–242s（< 600s 工具上限），前台直接跑即可，无需分段。故提示词
`_result_gate_section` 与 `_long_task_wait_section` 中的「有界入口（600s 内必返回）
优先前台直接跑」表述与实际能力一致。

## 全量回归失败归类（tasks 6.4）

`python3 bin/run_full_suite.py --timeout 3600 --baseline main`：

- 本次引入的失败：`test_admin::…injects_provider_env_when_assigned`、
  `test_daemon_lifecycle_races::…crash_writes_error_terminal`、
  `test_dashboard_data::…verify_config_roundtrip`、
  `test_system_settings_config::…structure_unchanged /…roundtrip` —— 全部为本次
  实现导致的严格相等断言/行为变化，已修复（`getattr(self,'config',{})` 防御 +
  测试锚点更新），复跑 5 passed。
- 存量失败（main 上也失败，BASELINE_FAILED 归类）：`test_callsite_arity_guard` /
  `test_daily_self_review` / `test_dashboard_api`(2) / `test_task_track`(4) ——
  与本次改动无关（环境性：git 不可用 / 静态服务 / task-track CLI 警告形态）。
- `test_v2_dev_server::…orphan_detected_when_no_claude`：主树与 worktree 均失败
  （git stash 复现），判定为环境性存量（node/pgrep 环境差异），非本次引入。