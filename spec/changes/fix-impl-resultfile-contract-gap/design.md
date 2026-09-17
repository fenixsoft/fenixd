# Design: fix-impl-resultfile-contract-gap

## Context

`agent_runner` 的产物硬门（`core/agent_runner/result_gate.py`）自 `add-judge-artifact-gate`（2026-09-14）
起对 implementer / fast-track 生效：`_check_impl_result_artifact` 要求 `<worktree>/.fenix-run-result.json`
存在、非空、可解析、`status` 在白名单内，且（success/partial 时）`completed_tasks` 与 tasks.md 勾选
一致、`unattainable` 申报合法。**判定侧完整，反馈侧缺失**。

提示词侧的产物契约段由 `PromptBuilder._result_gate_section()`（`core/agent_runner/prompt_builder.py:1548`）
生成，注入点仅三处：`planner-plan`（`:283`）、`planner-judge`（`:314`）、`spec-review`（`:345`）。
`implementer` 分支（`:258-273`）与 `fast-track` 分支均未注入（`spec-review` 版注释原文记载了同款
事故与处方，`prompt_builder.py:343-345`）。`git log -S"_result_gate_section"` 全仓仅 `948197d7`
（planner）与 `153fea1f`（spec-review）两次引入——**该缺口为原始状态，非回归**。

约束与既有设施：

- `_result_gate_section` 现按 `agent_type == "spec-review"` 早返回，否则一律返回 planner 路径文案
  （`planner_result_path(project_root, spec, "planner-judge"/"planner-plan")`）。实现者车道的结果
  文件在 **worktree 根**，不在 `.fenix/verify-progress/`，故必须新增一路径分派。
- 实现者提示词已有 `_task_progress_contract_section`（任务进度/诚实退出契约）与
  `_prev_error_section`（上轮 error）。`_result_gate_section` MUST 与前者共用「结果文件是交付物」
  口径、不与之矛盾；`_prev_error_section` 是死因透传的既有挂点。
- `_salvage_spec_review_result`（`runner.py:1209`）是既有捞回实现，路径与白名单均硬编码为
  spec-review；其调用点在 `core/pm_engine/spec_review.py:191/220`（评审车道终态处理）。
- `_classify_terminal_no_commit`（`runner.py:1162`）已实现「读转录末轮 assistant 文本 → 机械匹配
  假工具调用特征」的零 LLM 归因，正则常量 `_TERMINAL_NO_COMMIT_TOOL_PATTERN` 可直接复用。

## Goals / Non-Goals

**Goals**

1. 实现者双车道（implementer / fast-track）的提示词携带结果文件硬门契约，闭合「门在拦、提示词不说」
   的反馈断链（根因）。
2. 重试轮携带上一轮真实死因，消除「盲重派」。
3. 实现者车道具备 fenced-JSON 结果捞回，把「整轮白烧」降为「零成本回收」。
4. 结果文件缺失归因区分「格式回退截断」与「未收工即停」，提升事故可读性。

**Non-Goals**

- 不改硬门判定语义（白名单、completed_tasks 对账、unattainable 校验一律保持）。
- 不引入后台节拍机制（`ScheduleWakeup` 在 `-p` 模式下不产生唤醒；本变更只在契约段内**声明**这一
  事实并指向前台有界入口，不去修补 harness 能力）。
- 不治理 `Explore`/子代理模型不可用（`sonnet` 被网关 404）——那是 provider 路由议题，不在本 SPEC 范围
  （可在 todo.md 登记为独立条目）。
- 不做「结果文件缺失」时的自动重派语义变更（`fix-fasttrack-resultfile-missing-redispatch` 已在
  fast-track 车道立项处理「分支已有提交」的分支，本 SPEC 不与其重叠：本 SPEC 治的是**为什么会缺**）。

## Decisions

### D1: 契约段按 agent_type 分派路径，用「车道参数」而非新增函数

改造 `_result_gate_section(self, spec_name, agent_type="planner-judge", wt_path=None)`：新增 `wt_path`
可选参数，内部三分支——`spec-review`（既有早返回，行为逐字不变）、实现者族
（`agent_type in ("implementer","fast-track")` → `wt_path / ".fenix-run-result.json"`）、planner 族
（既有路径计算）。

- **为什么不让硬门侧也读同一个路径函数**：路径已由 runner 的 `_check_impl_result_artifact` 计算
  （`result_path = wt_path / ".fenix-run-result.json"`，`result_gate.py:437`）。为避免双实现漂移，
  在 `prompt_builder` 侧引入模块级 helper `impl_result_path(wt_path)` 并让契约段与硬门两侧共用，
  与既有 `planner_result_path` / `spec_review_result_path` 的「注入侧与校验侧同源」约定一致。
  但硬门侧在 `result_gate.py`、注入侧在 `prompt_builder.py`，两者都在 `agent_runner` 包内，
  提取到公共位置（如 `result_gate.py` 导出、`prompt_builder` 导入）即可，不新建模块。
- **`wt_path` 不总是可得**：`prompt_builder._build_prompt` 已接收 `wt_path`（`add-planner-efficiency`
  引入），runner 调用点（`runner.py:1906/1911`）已透传。契约段在 `wt_path is None` 时 MUST 降级为
  「相对路径 `.fenix-run-result.json`（worktree 根）」表述而非崩溃——降级路径仅供测试/异常场景，
  真实派发恒有值。

替代方案（否决）：在 `agents/implementer.md` 内静态写死契约段。否决理由：路径随 worktree 变化、
文案需与硬门同源；且 `fast-track` 与 `implementer` 共用一份文本，静态写死会与
`_task_progress_contract_section` 的「条件生成」范式分叉。

### D2: 契约段文案要素对齐 spec-review 版 + 三项实现者特有

复用 spec-review 版已验证的四要素（「唯一交付落点」「正文 JSON 不算交付」「未写/空/非法=判失败」
「先落盘再深入」），新增两项：

- **无后台节拍声明**：明示 `ScheduleWakeup` 在派发模式下不产生唤醒，长任务 MUST 用前台有界入口
  （`bin/run_full_suite.py --timeout 3600` 自身在有界时间内返回），MUST NOT「后台跑 + 轮询等」。
  依据：`impl-fix-observability-gaps-1789617176-a1`（$39.12）末轮正是「`Bash(run_in_background=True)`
  起套件 → 正文写假 `ScheduleWakeup` 等」的编排，套件跑完时 run 已终态。
- **先落盘再深入的时点绑定**：明确「全量套件回归之前先写结果文件」（现文案只说「深入调查之前」，
  实测事故恰恰发生在「先跑套件再落盘」的编排上）。

替代方案（否决）：只在 `agents/implementer.md` 步骤 7 后补一句「不写=判失败」。否决理由：静态
文件无法携带路径、无法按车道分派，且与既有动态契约段（任务进度）的分工范式不一致。

### D3: 死因透传走 `_prev_error_section` 扩展，不新增段

`_prev_error_section` 现读 `state_machine.read_one(spec_name)["error"]`，为空即零注入。扩展为
「`error` ∪ 上轮 `_impl_diagnosis`」合并渲染：

- 两者都有 → 两段分别呈现（error 在前，诊断摘要在后）；
- 仅诊断有 → 渲染诊断段（`attribution` / `conclusion` / `progress`）；
- 都没有 → 零注入（保持「首次派发提示词逐字不变」）。

**为什么合并不替换**：`error` 是执行器终态文本（含 `[provider-transient] 结果文件缺失...` 这类
可操作归因），`_impl_diagnosis` 是结构化摘要（含 `terminal` / `progress.branch` / `tasks_checked`）。
实测两者常**只有其一非空**（`fix-robustness-edge-cases` 有诊断无 error；
`fix-observability-gaps` 有 error 而诊断 `conclusion` 为空），合并是唯一能保证「重试轮总能拿到
死因」的形态。

风险：诊断是 JSON 字符串（`_impl_diagnosis` 以 JSON 文本存 STATE），渲染前 MUST 容错解析，
解析失败 MUST 降级为原文截断呈现而非抛错。

### D4: 捞回泛化为按车道取目标路径，白名单按车道分派

把 `_salvage_spec_review_result` 泛化为车道无关的 `_salvage_result_from_transcript(spec_name, run_id,
agent_type, wt_path)`，路径与白名单按 agent_type 分派（spec-review → 既有路径 + 评审白名单；
implementer/fast-track → `wt_path / ".fenix-run-result.json"` + `_IMPL_RESULT_STATUSES`）。

- **既有签名保留**：`_salvage_spec_review_result(spec_name, run_id)` 保留为薄包装（委派到泛化实现），
  因为 `core/pm_engine/spec_review.py` 经 `getattr(self.agent_runner, "_salvage_spec_review_result")`
  反射调用，且 `tests/test_review_circuit_breaker.py` 对其打桩——签名不得破。
- **调用点**：实现者车道的捞回挂点选在硬门判定**之前**、`_run_claude` 返回之后（与拷回前置同处，
  `runner.py:1963` 附近）；捞回成功则后续硬门自然放行。理由：此点已具备 `wt_path` 与 `sub_run_id`，
  且早于 `AgentArtifactGateError` 抛出。
- **不覆盖既有产物**：与 spec-review 版同语义（`path.exists() → return False`）。这条对实现者车道
  尤其重要——worktree 复用轮承载上一轮遗留产物是**设计预期**（见 `result_gate.py:304` 注释），
  覆盖会造成「上一轮成果被本轮半成品顶替」。

替代方案（否决）：在 `dispatch` 层做捞回。否决理由：dispatch 层无 `sub_run_id` 语义、且会与
`worktree` 生命周期解耦，硬门就在 runner 内，捞回离门越近越不易漏。

### D5: 归因复用既有特征常量，新增实现者车道调用点

在结果文件缺失的硬门失败分支（`AgentArtifactGateError` 捕获处，`runner.py:2019`）内，当
`agent_type in ("implementer","fast-track")` 且 error 文案为「结果文件缺失」时，调用既有的
`_classify_terminal_no_commit(sub_run_id)`（MUST 重命名或加别名以反映其通用性——该改名会影响
`tests/` 引用，实现时以 `grep` 确认后决定；保守做法是新增 `_classify_terminal_stall(sub_run_id)`
薄包装委派，避免破既有测试）。

**只改归因文案，不改控制流**：归因字符串拼进 error 前缀（形如
`[provider-transient] 结果文件缺失（未收工即停）...`），供日志/告警区分。MUST NOT 因归因类别不同
而改变重试次数、退避序列或 resume 决策。

## Risks / Trade-offs

- [契约段变长挤压注意力，模型可能忽略] → 文案控制在 12 行内、要素用 MUST 句式列举；且「先落盘再深入」
  置于段首（最先读到的位置）。
- [注入顺序打破既有段序测试] → `tests/test_scenario_static_check.py:414` 断言「场景静态缺陷情报」先于
  「结果文件硬门」（planner-judge 车道）。实现者分支注入点与 judge 无关，无冲突；但 MUST 跑该测试确认。
- [捞回代写的产物可能与 agent 真实进度不符] → 捞回只采信 `status` 在白名单且 `completed_tasks` 等
  字段**由 agent 自己写出**的 payload；框架不补字段。解释性风险：若 payload 与 worktree 真实状态不符，
  下游硬门的 `completed_tasks` 对账仍会拦截（捞回不绕过对账）。这是有意设计——捞回只解决「文件没落盘」，
  不解决「内容不实」。
- [`_prev_error_section` 扩展使提示词长度增长] → 诊断摘要 MUST 截断（建议 attribution ≤ 500 字、
  conclusion ≤ 800 字），避免重试轮提示词膨胀。
- [归因改名破坏既有测试] → 保守方案（新增薄包装）已写入 D5；若选择改名，必须全量 `grep` 并同步测试。
- [D1 路径 helper 提取位置不当引入循环导入] → `prompt_builder` 已 `from ...` 依赖 `result_gate`
  （同包），实现时确认导入方向；若成环则把 helper 放在 `prompt_builder` 并由 `result_gate` 导入
  （现状 `result_gate` 不导入 `prompt_builder`，此方向更安全）。

## Migration Plan

一次性注入，无数据迁移。

- 部署：修改提示词构建 + 捞回 + 归因三处；`agents/implementer.md` 同步收工契约措辞。
- 回滚：三处改动互相独立，可分别回滚；契约段注入为纯增量（无契约段的旧行为即现状）。
- 存量在飞 run 不受影响（提示词在派发时构建，新 run 才生效）。
- 验证：新增 `tests/test_impl_resultfile_contract.py` 覆盖四组 Scenario；回归
  `test_agent_prompt_files.py`、`test_review_artifact_first.py`、`test_agent_runner_gate.py`、
  `test_scenario_static_check.py`；全量走 `bin/run_full_suite.py --timeout 3600`。

## Open Questions

1. `_classify_terminal_no_commit` 是改名（语义通用化）还是新增薄包装？倾向**新增薄包装**
   `_classify_terminal_stall` 并让旧名委派，零测试破坏；实现时最终定夺。
2. 捞回是否应覆盖 `fast-track` 车道？倾向**覆盖**（同族硬门、同族死法，`fast-track` 的 F 阶段更长
   更易漏写），但 fast-track 结果文件含 `verification` 段、白名单相同，不需额外分支。
3. 契约段是否也要注入 `verifier` 车道？诊断显示 verifier 未出现该死法（其收工契约由
   `agents/verifier.md` 步骤 7/8 明示且已有 `verification-report.md` 双产物），本次**不纳入**，
   留待后续按证据决定。
