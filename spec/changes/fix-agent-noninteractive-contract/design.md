## Context

Fenix 全部 agent 经 `core/agent_runner/runner.py` 以 `claude -p --permission-mode bypassPermissions --output-format stream-json` 派发（headless、无人值守）。每个 run 的提示词由 `core/agent_runner/prompt_builder.py` 的 `PromptBuilder._build_prompt` 组装：

- **模板型路径**（implementer / verifier / fast-track / planner-plan / planner-judge / spec-review / administrator / dispute-judge）：加载 `agents/<agent-type>.md`（`AGENT_PROMPT_FILES` 白名单映射）→ 占位符填充 → 按 agent_type 追加动态段 → 追加项目级附加提示词段（`_project_extra_section`）。
- **独立构建路径**：`repair` / `self-review` / `evolution` 不走模板（`_build_repair_prompt` / `_build_self_review_prompt` / `_build_evolution_prompt`），在 `_build_prompt` 顶部早返回。

缺口：**没有任何 agent 契约声明「无法与人类交互」**。框架无法覆盖的 Claude Code 系统提示词却写着 `You are an interactive agent` 与「对难以撤销的操作先向用户确认（confirm first）」，SessionStart 注入的 superpowers skill 又反复出现 `plan mode` / `brainstorming` 等交互式措辞。2026-09-17 `refactor-long-functions` 的 implementer run 因此在演示完计划后 `end_turn` 等待确认（「我是否继续执行这个计划？确认后我将开始实现 B9+B10 提取。」），工作树无 `.fenix-run-result.json` → 判失败 → 原地重派，整轮 token + 已完成实现进度重烧。全仓 2002 份转录中此类收尾 2 份，均为 implementer。

## Goals / Non-Goals

**Goals:**
- 为**所有** agent 类型（含独立构建路径）注入一段统一、非交互契约，明确「无人可问」并禁止「请求人类确认后停止」。
- 契约段为**单一真相**：新增 agent 类型自动继承，不需要逐个改 `agents/*.md`。
- 注入实现可测试、对既有提示词语义零破坏（不改白名单、不改动态段、不改模板文件）。

**Non-Goals:**
- 不修改 SessionStart 注入的 superpowers 机制（外部插件，范围外）——契约段内显式声明 `plan mode`/`brainstorming` 在 Fenix run 不适用即可。
- 不重构 `agents/*.md` 模板文件（中央段已覆盖）。
- 不改变任何结果文件契约、状态机语义或失败出口（`partial`/`error`/`verified` 等）。

## Decisions

### D1：中央代码段注入，而非逐个模板文件

在 `PromptBuilder` 新增 `_noninteractive_contract_section() -> str`（纯函数，返回固定契约文本），于 `_build_prompt` 的**统一收尾处**（`_project_extra_section` 之前）无条件追加。

**理由**：`AGENT_PROMPT_FILES` 是 agent 类型白名单的单一来源，覆盖所有模板型 agent；一处注入，新增类型自动继承。备选（逐个 `agents/*.md` 顶部写契约）改动面大、10 份易漂移，且 repair/self-review/evolution 不吃模板、需另补——否决。

**注入位置**：置于 agent_type 特异动态段与 administrator 段之后、`_project_extra_section` 之前。保护既有约定「项目级附加提示词段位于 prompt 末尾」（`tests/test_agent_prompt_files.py::test_project_extra_appended` 断言 `prompt.rstrip().endswith(...)`），本段不得插到项目附加段之后。

### D2：独立构建路径同步接入

`_build_repair_prompt` / `_build_self_review_prompt` / `_build_evolution_prompt` 三条早返回路径各自 `return` 前追加 `_noninteractive_contract_section()`，确保 requirement「所有 agent 类型」成立。备选（把三条路径改为统一收尾）改动大且牵动早返回结构——否决，就地追加最小。

### D3：契约段文本内容

固定中文文本（与 `agents/*.md` 及动态段语汇一致），含四组语义：无人类可交互 / 无人值守、直接执行不请求批准、禁止为等待回复而结束回合并按本车道失败出口收工、显式覆盖系统提示词默认框架。文本为常量，不做占位符替换（无 spec 维度信息需求）。

### D4：测试

新增 `tests/test_agent_noninteractive_contract.py`，覆盖：模板型各类型均含契约段（参数化遍历 `AGENT_PROMPT_FILES` 键）、独立构建三路径均含、契约段关键语义串在场、`_noninteractive_contract_section()` 幂等可重复注入。同步更新 `tests/test_agent_prompt_files.py::test_absent_agents_dir_zero_injection` 的手工 baseline（该测试逐字节比对完整 prompt，需把新段纳入 baseline）。

## Risks / Trade-offs

- [既有逐字节 prompt 比对测试被打破] → `test_absent_agents_dir_zero_injection` 的手工 baseline 同步加入新段（D4 已列为交付项）；其余测试为「包含」断言（`in prompt`），不受新增段影响。
- [契约段与系统提示词冲突（系统说「交互式、确认优先」）] → 契约段显式点破该默认不适用（D3 第 4 组语义），以框架注入文本的优先级覆盖之。
- [段文本过长稀释其它契约] → 控制在一屏内（约 10 行），只保留规范性语义。
- [独立路径漏接] → D2 显式三条 + D4 参数化断言「三路径均含」。
- [未来新增 agent 类型漏接] → 中央段在 `_build_prompt` 统一收尾处注入，新增模板型类型自动继承（D4 遍历白名单键断言）。

## Migration Plan

无数据迁移。部署即生效——下一次 daemon 派发任一 agent 时新段即在提示词内。回滚 = revert 本 change 的提交（纯提示词增段，无状态机/产物影响）。

## Open Questions

- 无。
