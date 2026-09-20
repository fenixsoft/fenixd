# Design: fix-agent-lane-efficiency

## Context

本 SPEC 只处理**工程侧**浪费（模型吞吐不在范围内）。四类证据全部来自 `.fenix/runs/archive/` 的事件级转录复核（29 份 run，$524.6），每类均有确定的失败形态与可定位代码点：

| 现象 | 取证 | 代码点 |
|---|---|---|
| `Explore` 子代理 24/24 失败 | `task_notification` 含 `model_not_found (HTTP 404, model sent: claude-opus-4-8)` | `core/agent_runner/runner.py:_build_isolated_settings`（刻意不注入模型映射） |
| 单工具调用 / 重复读 | 503 tool_use / 391 assistant 消息；重复 Read 159、Edit 176、Bash 179；28% tool_result 字节 >20KB | `core/agent_runner/prompt_builder.py` 各契约段无效率约束 |
| 上下文 O(N²) | 最贵 spec-review run：脚手架 17.4K/turn + 对话累积（末轮 82.5K）→ 197 轮 12.16M input（28% 脚手架 / 72% 重放） | 提示词缺「取证深度上限」；无逐 run 上下文指标 |
| 前缀缓存不可依赖 | `cache_control` 写入后同前缀二次调用 `cache_read` 仅 113（inferaiapi）或恒 0（maomaoai/bigmodel/deepseek） | 网关侧（**非**框架缺陷，见 D3） |
| 600s 工具超时自旋 | 10 次超时；`sleep → echo RUNNING` 编排原文 | `prompt_builder.py:_result_gate_section` 的「无后台节拍」措辞 |

关键事实（决定 D4）：后台 Bash 任务的**完成通知是真实投递的**——转录中存在成对的 `task_notification`（如 `bvqufrbm3`「背景命令 … completed (exit code 0)」）。因此「无后台节拍」这一表述与实际能力不符，正是 `sleep` 轮询反模式的来源。

## Goals / Non-Goals

**Goals**
- 恢复子代理并行探测原语，消除 404 失败与其隐性串行化后果。
- 以降**轮数**（一阶杠杆）为主、降每轮增量为辅，压低长车道上下文成本。
- 以前缀缓存**机械探针**替代猜测，并把「不可依赖缓存」固化为结论，止住重复投入。
- 消除 600s 工具上限引出的自旋等待。

**Non-Goals**
- 不优化模型本身的吞吐/延迟（另属网关侧议题）。
- **不做缓存优化**（D3 已定案：网关不产生可复用命中；仅保留探针用于未来复验）。
- 不在点2引入框架侧工具拦截（仅提示词层引导）。
- 不重构 `_run_claude` 流式处理时序（指标为纯读侧旁路）。
- 不新增 spec 级预算/熔断机制（已由 `fix-redispatch-loop-governance` 覆盖）。

## Decisions

### D1 子代理模型映射：按 provider 重建，而非盲抄 cc-switch env

**问题**：`_build_isolated_settings` 的既有注释（`runner.py:1185`）明说「不复制 `~/.claude/settings.json` 的 env（`ANTHROPIC_DEFAULT_*` / `CLAUDE_CODE_SUBAGENT_MODEL`）——会毒化子代理模型解析（陈旧 hy3）」。该决定正确，但**只做了一半**：不清除旧映射的同时也没有**建立新映射**，于是子代理 tier 解析落回宿主进程 env 的 cc-switch 官方名（`claude-opus-4-8[1M]`），直连 provider 无此模型 → 404。

**决定**：在 provider 隔离 `settings.json` 写入一段**按该 provider 重算**的 `env`，把子代理相关 tier 全部映射到 provider 自身可用模型：

- `CLAUDE_CODE_SUBAGENT_MODEL` = 子代理模型（配置键优先，缺省 = provider 的 `model`）；
- `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL` 同理映射到 provider `model`（避免任何 tier 解析回落到宿主 cc-switch 名）。

与既有注释不矛盾：这是**provider 作用域内重建**的映射，不是复制宿主映射。关闭既有「陈旧 hy3」风险的方式是把值钉死在 provider 配置而非宿主环境。

**配置键**：新增 `agents.subagent_model_override`（缺省空 = 用 provider `model`）。**必须**同步 Dashboard 设置页 UI（配置键与 UI 同步铁律）。

**失败可见化**：子代理启动失败（如仍 404）MUST 在 run 转录落显式 WARNING/告警事件，MUST NOT 静默吞掉——现状是失败只体现为 `task_notification` 的 failed 态，模型与运维都难以及时归因。

**备选**：在 `_run_claude` 的进程 `env_overrides` 注入而非 settings.json。取舍：进程 env 与 settings.json `env` 两条通道的优先级需实测确认（既有记忆：settings.json `env` 覆盖子进程 env）。实现阶段 MUST 以实测确定生效通道，并在设计记录结论。

### D2 工具调用效率 + 取证深度上限（点2 与点3 合流）

**实测分解**（$72.9 的 spec-review run，197 轮）：

| 成分 | 量 | 对 12.16M input 的贡献 |
|---|---|---|
| 固定脚手架（CLI 系统提示 + 工具定义） | 17.4K/turn（空会话实测，与 skills/plugins 无关） | 3.4M（28%） |
| 对话累积回放 | 末轮 82.5K，线性增长 | 8.1M（72%） |
| `agents/spec-review.md` 本体 | 10.7KB ≈ 2.7K/turn | 0.5M（4%） |

结论：**压轮数是一阶杠杆**；砍提示词文件（4%）与砍脚手架（28% 中可动的部分，且为 CLI 内建）收益都远小于压轮数。

**决定**：注入规范性提示词（不设框架拦截），四条：

1. **批量并行**：同一轮内相互独立、无数据依赖的工具调用 MUST 合并为一个批次提交；
2. **定向读取**：优先 `Grep` / 带范围 `Read`；MUST NOT 反复整文件读取未变更大文件；同 run 内已读且未变更的文件 MUST NOT 重复读取；
3. **取证深度上限**：取证 MUST 以「最小可判反证」为限——足以判定 `blocking` vs `repairable` 即可，MUST NOT 为完整复现 SPEC 的每条断言而穷尽探测/重跑；
4. **输出裁剪**：探针/命令输出 MUST 裁剪（`head -c` / 取关键行 / 落临时文件只回读关键片段），MUST NOT 将数十 KB 原始输出整块进对话。

**理由**：该 run 160 次 Bash 中 **63 次是 OCR 超时复现探针**，是对话累积的主因；而提示词中**已有**「执行效率」段（并行/一步到位/不重复求证）却仍打 160 次，说明现有措辞缺「深度上限」这一条——模型把「取证义务」理解为穷尽复现。补上限即可。

**备选**：框架侧拦截（如拒绝超大 Read / 强制合并）。取舍：易误伤合法大文件读取，且与「不改流式时序」的 Non-Goal 冲突；用户明确选择仅提示词引导。效果以轮数/重复读指标回归观察。

### D3 前缀缓存：探针定案「不可依赖」，不做缓存优化

**问题**：缓存低命中是否可由框架侧修复？（此前不确定是网关剥离还是框架未设置。）

**探针实测（定案）**：直连各 provider 的 `/v1/messages`，构造 ~6K token 的稳定前缀：

| 序列 | input | cache_read | cache_creation |
|---|---|---|---|
| 有 `cache_control` 第1次 | 19 | **6144** | 0 |
| 有 `cache_control` 第2次（同前缀） | 6350 | **113** | 0 |

多轮 CLI 探针（`--resume` 续同一 session）：`inferaiapi.com` / `bigmodel.cn` / `deepseek` 的 `cache_read` **恒为 0**。

**结论**：网关**接受** `cache_control` 并写入缓存（第1次 cr=6144），但**写入的缓存不可复用**（第2次仅命中 113，即 system 段的小量）；全 provider 一致。故缓存不可依赖，**框架侧无需也无法修复**。

**决定**：
1. **不做缓存优化**——明确写入 Non-Goals，避免后续重复投入。
2. **保留可复现探针** `bin/probe_prompt_cache.py`（输出 JSON 判据），供网关升级后复验；探针结论落文档。
3. **转向 token 经济性可观测**：run 末落逐 run 指标（轮数 / 上下文峰值 / input / cache_read），在 `context_cost_per_turn` 超阈值时打诊断告警，使 O(N²) 结构可见、防回归。

**记账告警（重要）**：实测网关的 token 记账自相矛盾——同一 run 的 `modelUsage.cacheReadInputTokens` 记 1.2 亿而 `result.usage.cache_read_input_tokens` 记 1200 万。故**具体金额**不可全信，但「轮数×上下文的 O(N²) 结构」是转录事实。实现阶段以转录事件为指标来源，不以 `modelUsage` 金额为准。

### D4 长任务：后台单次等待，禁止 sleep 自旋

**决定**：修正 `_result_gate_section` 的实现者分支措辞：
- 删除「无后台节拍」表述（与实际通知能力不符）；
- 改为：可能超过 600s 的任务 MUST 用**一次** `run_in_background: true` 启动，然后**继续独立工作或等待完成通知**；MUST NOT 用 `sleep` / 周期性 `ps` 轮询；
- 有界入口（`bin/run_full_suite.py --timeout`）若能在 600s 内返回则前台直接跑。

**理由**：`sleep → echo RUNNING` 自旋的根因是把「后台等待」当违规，逼迫模型用前台 sleep 模拟等待。后台通知已在既有链路可用，无需新机制。

**备选**：框架侧把长命令自动降级为后台并注入轮询。取舍：改动面大且与「不改流式时序」冲突；提示词修正成本最低、可立即观测轮次下降。

## Risks / Trade-offs

- [provider 不支持子代理模型映射，注入仍 404] → D1 的失败可见化保证告警不静默；探针可扩测子代理通道。
- [提示词引导对模型无约束力（现有「执行效率」段已存在却仍 160 次调用）] → 以轮数/重复读/上下文峰值指标回归观察；无效则升级为框架侧护栏（本次不做）。
- [新增配置键遗漏 UI] → 配置键与 Dashboard UI 同步为强制任务项。
- [上下文指标阈值过紧误告警] → 阈值取保守值，仅日志/诊断告警，MUST NOT 阻断 run（告警降噪铁律）。
- [探针结论随网关升级失效] → 探针可重复执行；结论仅作「当前不可依赖」记录，非永久契约。

## Migration Plan

1. 落地代码 + 测试；`bin/probe_prompt_cache.py` 对各 provider 跑一轮，记录结论。
2. 落位 `restart_request` 信号；supervisor 消费后重启 daemon 生效。
3. 回滚：移除配置键回缺省 + revert 注入代码；上下文指标与探针为纯读侧，无副作用。

## Open Questions

- 子代理模型映射的生效通道（settings.json `env` vs 进程 `env_overrides`）——实现阶段实测钉死并记录。
- `context_cost_per_turn` 告警阈值的具体取值——实现阶段以本次 29 份 run 的分位数定标。
