## Why

Fenix 的全部 agent 都以 `claude -p`（headless、无人值守、`bypassPermissions`）运行，但存在一条贯穿所有 agent 类型的提示词缺口：**没有任何 agent 契约声明「你无法与人类交互」**。于是部分 run 会以「请求人类确认」收尾——2026-09-17 `refactor-long-functions` 的 implementer run 在完成大部分提取后，末条输出为「我是否继续执行这个计划？确认后我将开始实现 B9+B10 提取。」并 `end_turn`，等待一个永远不存在的人回复；工作树无 `.fenix-run-result.json` → 框架判失败 → 原地重派，整轮 token 与已完成的实现进度一并重烧。全仓 2002 份 agent 转录中，以「请求人类确认」收尾的有 2 份，且**都是 implementer**——同一缺口在其它的 agent 类型上只是恰好尚未触发。

根因是「提示词真空 × 环境提示词主动诱导」：框架注入的 agent 提示词通篇是任务指令、从不提「无人可问」；而框架无法覆盖的 Claude Code 系统提示词却明确写着 `You are an interactive agent` 与「对难以撤销的操作先向用户确认」，SessionStart 注入的 superpowers skill 又反复出现 `plan mode` / `brainstorming` 等交互式工作流措辞。模型据此推断自己身处一个可交互的规划会话，遂演示计划后停下等人。

## What Changes

- 在提示词构建层（`core/agent_runner/prompt_builder.py`）**新增一个中央「非交互契约」段**，为**所有 agent 类型**（含走独立构建路径的 repair / self-review / evolution）统一追加该契约段：
  - 你是无人值守的 headless agent（`claude -p`），**没有能回答你的人**；任何「是否继续 / 请确认 / 等待回复」都会整轮空转、被判失败并重烧预算。
  - 遇到计划或分叉：**直接执行**，不请求批准；难以撤销的操作按 SPEC/tasks 授权推进，事后在结果文件/处置记录中留痕。
  - 禁止为「等人回复」而结束回合（`end_turn`）；要么继续推进，要么按各自契约的失败出口（`partial` / `error` / 相应终态）收工。
  - 显式覆盖系统提示词默认框架：`interactive agent` / 「难以撤销的操作先确认」等在 Fenix run 中**不适用**。
- 中央段为**单一真相**：agent 类型 → 提示词模板的映射（`AGENT_PROMPT_FILES`）新增类型时自动继承，无需改模板文件。
- 不做：不修改 SessionStart 注入的 superpowers 机制（属外部插件，本 SPEC 范围外）；重构各 `agents/*.md` 文件（中央段已覆盖，模板保持不动）。

## Capabilities

### New Capabilities
- `agent-noninteractive-contract`: 定义「所有 headless agent 提示词 MUST 携带非交互契约段、且该段对所有 agent 类型生效（含独立构建路径）」的可测试需求。

### Modified Capabilities
<!-- 无既有 spec 的 requirement 级改动 -->

## Impact

- **代码**：`core/agent_runner/prompt_builder.py`（新增契约段构造 + 在 `_build_prompt` 的统一注入点接入；`_build_repair_prompt` / `_build_self_review_prompt` / `_build_evolution_prompt` 三条独立构建路径同步接入）。
- **测试**：新增 `tests/test_agent_noninteractive_contract.py`（覆盖所有 agent 类型均含契约段、独立构建路径亦含、段内容含关键语义）。
- **行为影响**：所有 agent run 的提示词新增一段；预期收敛「请求人类确认后停下」这一类空转（现状 2002 份转录中 2 份，均 implementer）。
- **无破坏性**：不改变 `AGENT_PROMPT_FILES` 白名单、不改任何结果文件契约或状态机语义；模板文件不动。
