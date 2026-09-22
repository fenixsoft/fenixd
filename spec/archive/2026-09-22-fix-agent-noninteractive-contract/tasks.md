# Tasks: fix-agent-noninteractive-contract

## Deliverables

```yaml
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: tests/test_agent_noninteractive_contract.py
  kind: new
- path: tests/test_agent_prompt_files.py
  kind: modify
```

## 1. 中央非交互契约段

- [x] 1.1 在 `core/agent_runner/prompt_builder.py` 的 `PromptBuilder` 新增 `_noninteractive_contract_section(self) -> str`：返回一段固定中文「非交互契约」文本，含四组语义——（a）你是无人值守的 headless（`claude -p`）agent，不存在能回复你的人类；（b）遇计划或分叉直接执行、不请求批准，难以撤销的操作按 SPEC/tasks 授权推进并在结果文件/处置记录留痕；（c）禁止为等待人类回复而结束回合，无法继续时按本车道契约的失败出口（`partial`/`error`/相应终态）收工；（d）Claude Code 系统提示词中的 `interactive agent` 与「难以撤销的操作先确认」等默认框架在 Fenix run 中**不适用**（含显式点名 `plan mode`/`brainstorming` 交互式工作流不适用）
- [x] 1.2 在 `_build_prompt` 的统一收尾处（agent_type 特异动态段与 administrator 段之后、`self._project_extra_section(...)` 调用之前）无条件 `prompt += self._noninteractive_contract_section()`，使全部模板型 agent（implementer / verifier / fast-track / planner-plan / planner-judge / spec-review / administrator / dispute-judge）自动继承；不得置于 `_project_extra_section` 之后（保护「项目级附加段位于 prompt 末尾」既有约定）
- [x] 1.3 在三条独立构建路径 `_build_repair_prompt` / `_build_self_review_prompt` / `_build_evolution_prompt` 的 `return` 之前各自 `+= self._noninteractive_contract_section()`，使 repair / self-review / evolution 同样携带契约段

## 2. 测试

- [x] 2.1 新增 `tests/test_agent_noninteractive_contract.py`：参数化遍历 `AGENT_PROMPT_FILES` 全键，构造最小 project 夹具后调用 `runner._prompt_builder._build_prompt(spec, agent_type)`，断言每个模板型 agent 的提示词均含契约段关键锚点串（如「非交互契约」标题与「没有」/「无人」等无人类语义串）
- [x] 2.2 同文件新增用例：对 `repair` / `self-review` / `evolution` 三条独立构建路径，分别经 `_build_repair_prompt` / `_build_self_review_prompt` / `_build_evolution_prompt` 产出提示词，断言同样包含契约段锚点串
- [x] 2.3 同文件新增用例：断言契约段文本含四组规范性语义（无人类可交互 / 直接执行不请求批准 / 禁止为等待回复而结束回合 / 显式覆盖系统提示词 `interactive agent` 默认），逐串断言在场
- [x] 2.4 同文件新增用例：断言 `_noninteractive_contract_section()` 幂等——对同一 PromptBuilder 连调两次返回相等字符串
- [x] 2.5 更新 `tests/test_agent_prompt_files.py::test_absent_agents_dir_zero_injection` 的手工 baseline：把 `_noninteractive_contract_section()` 纳入逐字节比对的期望串，使该用例在新段注入后仍通过

## 3. 收尾

- [x] 3.1 运行 `python3 -m pytest tests/test_agent_noninteractive_contract.py tests/test_agent_prompt_files.py tests/test_impl_resultfile_contract.py tests/test_fast_track_prompt.py -q` 全绿，确认既有提示词「包含」断言零回归
- [x] 3.2 自查满足 spec 全部 Scenario（所有类型含契约段 / 独立路径含 / 段含四组语义），并核对 `## Deliverables` 声明与实现分支实际改动一致
