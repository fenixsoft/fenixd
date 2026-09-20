# Tasks: fix-agent-lane-efficiency

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/AgentModelPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: agents/implementer.md
  kind: modify
- path: agents/fast-track.md
  kind: modify
- path: agents/spec-review.md
  kind: modify
- path: bin/probe_prompt_cache.py
  kind: new
- path: tests/test_subagent_model_injection.py
  kind: new
- path: tests/test_run_token_economy.py
  kind: new
- path: tests/test_prompt_lane_efficiency_sections.py
  kind: new
- path: docs/help/09-config.md
  kind: modify
```

> 注 1（路径确认）：`core/dashboard/static/src/pages/settings/components/` 下已存在 `AgentModelPanel.tsx` / `ParallelSettingsPanel.tsx`（2026-09-20 实测）。子代理模型配置键的 UI MUST 落在既有的模型/并行设置面板之一（实现者按面板语义择一，并在实现记录中注明选择）；若该目录结构已随前序 SPEC 变更，则按符号名在对应面板修改。
>
> 注 2（行数契约）：`core/agent_runner/runner.py` 受 `tests/test_agent_runner_modules_contract.py` 的行数断言约束（阈值 `< 4000`）。本 SPEC 的 runner.py 增量 MUST 尽量下沉到 `result_gate.py` 等既有模块，MUST NOT 为腾行数做无关重构。
>
> 注 3（缓存探针结论）：`bin/probe_prompt_cache.py` 的结论（网关不支持可复用前缀缓存）已在 design D3 定案并记录；实现者只需把探针落地为可重复执行的脚本，**MUST NOT** 据此改任何派发/路由行为。
>
> 注 4（硬门顺序）：本次新增动态契约段 MUST 置于项目级附加段之前，且 MUST NOT 破坏 `test_impl_resultfile_contract.py` / `test_agent_prompt_files.py` 的既有顺序断言。

## 1. 子代理模型解析兜底

- [ ] 1.1 在 `core/agent_runner/runner.py` 的 `_build_isolated_settings`（及 `_ensure_agent_config_dir` 的落盘路径）注入按 provider 重算的模型映射：`CLAUDE_CODE_SUBAGENT_MODEL` 与 `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL` 均映射到 provider 自身模型，取值优先级为 `agents.subagent_model_override`（非空）→ provider 的 `model`；MUST NOT 复制宿主 `~/.claude/settings.json` 的模型名（防陈旧映射毒化）
- [ ] 1.2 实测确定生效通道（settings.json `env` vs 进程 `env_overrides`）并把结论写入实现记录；若实测表明 settings.json `env` 不生效，则改走能确定性生效的通道并说明依据
- [ ] 1.3 未分配 provider（默认网关车道）路径行为 MUST 逐字节不变：补测断言证明该路径不写入上述 provider 隔离映射
- [ ] 1.4 子代理启动失败可见化：捕获子代理 `model_not_found` / 认证 / 启动期错误，在 run 转录与 daemon 日志落含子代理类型与错误类别的 WARNING；MUST NOT 改变该 run 的终态判定

## 2. 配置键与 Dashboard UI

- [ ] 2.1 在 `core/config.py` 新增 `agents.subagent_model_override` 读取器（缺省空串；空 = 用 provider model），并在 `.fenix/config.template.yaml` 的 `agents` 段补注释与示例值
- [ ] 2.2 在 `core/dashboard/data/config_admin.py` 把 `agents.subagent_model_override` 纳入受管键白名单（读取回显 + 写入合并保留其它 `agents` 子键），保持既有严格相等断言为绿
- [ ] 2.3 在设置页面板（`AgentModelPanel.tsx` 或语义最合的既有面板）新增该键的输入控件与保存调用，`dashboard.ts` 补服务函数；跑 `npm run build` 确认前端构建通过
- [ ] 2.4 在 `docs/help/09-config.md` 补充该配置键说明（作用、缺省、与 provider 模型的关系）

## 3. 工具调用效率与取证深度契约段

- [ ] 3.1 在 `core/agent_runner/prompt_builder.py` 新增「工具调用效率」段：批量并行、定向读取（`Grep`/带范围 `Read`）、同 run 去重三条 MUST 句式
- [ ] 3.2 新增「取证深度上限与输出裁剪」段：取证以最小可判反证为限（评审 MUST NOT 为完整复现穷尽探测）、大块输出 MUST 裁剪后入对话
- [ ] 3.3 将 3.1 / 3.2 两段按 agent_type 注入 `implementer` / `fast-track` / `spec-review` 车道，位置在项目级附加段之前；条件不满足时返回空串（零注入）
- [ ] 3.4 在 `agents/implementer.md` / `agents/fast-track.md` / `agents/spec-review.md` 同步效率与取证深度约束的措辞（与动态段同源，不重复计数）

## 4. 上下文经济性指标与缓存探针

- [ ] 4.1 在 `_run_claude` 流式读取环内以纯读侧方式累计轮数 / 上下文峰值估算 / `input_tokens` / `cache_read_input_tokens`；run 终结时（成功/失败/取消三路径）落一行 `{"type": "run_metrics", ...}` 指标事件（终态行之后追加，不改既有行顺序）
- [ ] 4.2 指标超阈值（`per_turn_input_tokens`）时打诊断 WARNING（含 run_id 与实测值），MUST NOT 阻断 run、MUST NOT 触发独立人工告警；阈值以本次 29 份 run 的分位数定标并写入实现记录
- [ ] 4.3 新增 `bin/probe_prompt_cache.py`：对配置内指定 provider 发带 `cache_control` 的稳定前缀两轮请求，解析第二轮 `cache_read_input_tokens`，输出 JSON 判据（`provider` / `cache_supported` / `evidence`）；可离线对任一 provider 执行，不依赖 daemon
- [ ] 4.4 在 `agents/spec-review.md` 的执行效率段补齐「取证深度上限」措辞（现有段已有并行/一步到位/不重复求证，缺深度上限），并确保与 3.2 的动态段不矛盾

## 5. 长任务前台有界等待

- [ ] 5.1 修正 `_result_gate_section` 的实现者分支：删除「本车道无后台节拍」表述，改为「一次 `run_in_background` 启动 + 等待完成通知或并行独立工作；MUST NOT 用 `sleep` / 周期性 `ps` 轮询；有界入口优先前台直接跑」
- [ ] 5.2 确认 `bin/run_full_suite.py` 的 `--timeout` 语义为「自身在超时内返回」，若实测其可能超过 600s 则改为分段返回或明确契约（在实现记录中登记实测结论）
- [ ] 5.3 在 `agents/implementer.md` / `agents/fast-track.md` 同步前台有界等待措辞，删除与后台能力矛盾的表述

## 6. 测试与收口

- [ ] 6.1 新增 `tests/test_subagent_model_injection.py`：断言直连 provider 时隔离 settings 含 provider 模型映射、配置键覆盖生效、默认网关路径零写入
- [ ] 6.2 新增 `tests/test_run_token_economy.py`：断言 run_metrics 指标行落盘位置与字段、超阈值告警不阻断、既有读侧不受影响
- [ ] 6.3 新增 `tests/test_prompt_lane_efficiency_sections.py`：断言三条效率/取证深度/长任务段在对应车道的注入与顺序不变式
- [ ] 6.4 全量回归走有界入口 `python3 bin/run_full_suite.py --timeout 3600 --baseline main`，失败逐项归类存量/引入并写入实现记录（`runner.py` 行数断言 MUST 保持为绿）
- [ ] 6.5 逐项核对 `## Deliverables` 与实现分支实际文件一致（new 文件存在、modify 文件有改动）
- [ ] 6.6 落位 `restart_request` 交付物（仓库根路径，JSON：`reason` / `origin` / `date`）并冒烟预演（全新进程 `import core.agent_runner.prompt_builder` + `import core.agent_runner.runner` + 断言效率段与子代理映射在位），实际重启由 supervisor 消费该信号完成
