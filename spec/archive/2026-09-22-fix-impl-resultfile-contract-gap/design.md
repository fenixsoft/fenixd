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
2. 重试轮携带上一轮真实死因（两来源可达、单次渲染不重复），消除「盲重派」。
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
- **helper 落位方向（实测，不可反）**：既有依赖方向是 `result_gate` → `prompt_builder`——
  `result_gate.py:23-28` 从 `prompt_builder` 导入 `planner_result_path` /
  `spec_review_result_path` / 两个白名单；`prompt_builder` 不导入 `result_gate`。故
  `impl_result_path` MUST 与既有路径函数同处 `prompt_builder.py`，由 `result_gate` 导入使用。
  反向（helper 落 `result_gate.py`、`prompt_builder` 导入）会形成循环导入，并使
  `tests/test_agent_runner_modules_contract.py:71`「单独 import 三模块不触发循环 import」契约红。
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

### D3: 死因透传——先核实既有两段覆盖，再最小补齐（MUST NOT 重复渲染）

**实测现状复核（2026-09-17，与本 SPEC 初判不同，以此为准）**：实现者双车道的重派提示词**已由两段**
携带上轮死因——

- `_prev_error_section`（`prompt_builder.py:609`）读 `STATE.error`，注入点 `:260`（implementer）/
  `:334`（fast-track）；产物硬门失败文本经 `[provider-transient]` 前缀（`runner.py:2033-2034`）
  后由 `dispatch.py:1319-1333` 写入 `STATE.error`；
- `_impl_diagnosis_section`（`prompt_builder.py:574`）读 STATE `_impl_diagnosis`，注入点 `:263` /
  `:336`；该字段由 `dispatch.py:867` 在每次 run 终结时写入，其 `attribution` 即
  `final_error[:500]`（`dispatch.py:1538-1603`）。

即「`STATE.error` 与 `_impl_diagnosis` 两处口径不通」**不成立**，两条来源在重派轮通常都可见。
因此 D3 **不再新增任何与 `_impl_diagnosis_section` 重复的诊断渲染**，只保留两件确有价值的事：

1. **写点核实（原 task 2.3）**：确认「结果文件缺失」文本确经上两条来源到达重派轮；若某路径上
   `STATE.error` 被其它写点覆盖（`dispatch.py` 存在多处 `{"error": ...}` 写点），定位写点并保证
   死因不丢（实现记录写明实际取值来源）。
2. **零重复约束（字段级，2026-09-17 评审明确口径）**：若为覆盖「仅 `error` 非空、诊断为空」的边角
   仍要扩展 `_prev_error_section`，同一诊断字段（`attribution` / `conclusion` / `progress`）MUST NOT
   被两段**各自作为独立条目**渲染——`_impl_diagnosis_section` 已渲染诊断时，`_prev_error_section`
   MUST 只渲染 `error` 原文、MUST NOT 追加任何诊断字段条目。否则两段叠加会让重试轮提示词出现两份
   诊断，与本设计「避免提示词膨胀」的风险项自相矛盾。
   **判据是字段级、不是子串级（MUST 遵守）**：`attribution` 的定义即 `final_error[:500]`
   （`dispatch.py:1538-1603`），而同一路径上写入 `STATE.error` 的也是 `final_error`
   （`dispatch.py:1319-1333`）——故 `error` 原文**天然包含** `attribution` 子串。这是两字段同源所致，
   MUST NOT 计作「重复渲染」，MUST NOT 为凑「内容只出现一次」而裁剪 / 丢弃 `error` 原文
   （那会违反本 SPEC「上轮死因 MUST 可达」的硬要求，并连带击穿 task 2.3 的透传验收）。

替代方案（否决）：把 `_impl_diagnosis_section` 的渲染职责并入 `_prev_error_section` 并删除前者
——`tests/test_run_budget_continuity.py:110-144` 对该段有独立断言，删除会破既有护栏。

**仍然存在但本 SPEC 不主张修复的真缺口**：同一 dispatch 内的**原地退避重试 attempt**
（`runner.py:1884` 子循环）会重建 prompt，而 `STATE.error` / `_impl_diagnosis` 只在 dispatch 终结时
写入（`dispatch.py:867`）——故 attempt 2+ 看不到 attempt 1 的失败原因。修复它需在 runner 内把上次
attempt 的 error 传进 `_build_prompt`（控制流改动）；本 SPEC 只在 task 2.3 登记该事实与取值来源。

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

两条硬约束（实现时 MUST 遵守，否则与既有模块契约/测试冲突）：

- **落位与签名**：`result_gate.py` 的模块契约（文件头注释 + D2b）明确「本模块 MUST NOT
  `import runner`；门族函数首参为 `runner` 实例」。故若把可复用入口落在 `result_gate.py`，签名
  MUST 为 `classify_terminal_stall(runner, sub_run_id)`（经实例访问 `runner._TERMINAL_NO_COMMIT_TOOL_PATTERN`），
  MUST NOT 写成 `classify_terminal_stall(run_file)` 后去 `import runner`；最保守形态是保留
  `AgentRunner._classify_terminal_no_commit` 为唯一实现，仅新增一层文案映射/别名。
- **文案是新增映射，不是既有返回值**：既有方法无假工具调用特征时返回「未提交即收工」
  （`runner.py:1193/1198`），本 SPEC 的实现者车道归因要求「未收工即停」。两者 MUST 通过显式映射
  共存——MUST NOT 直接改既有方法返回值（`tests/test_terminal_nocommit_gate.py:196/203` 断言
  「未提交即收工」，改则破既有护栏）。

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
- [D1 路径 helper 提取位置不当引入循环导入] → 实测依赖方向为 `result_gate` → `prompt_builder`
  （`result_gate.py:23-28` 导入 `planner_result_path` / `spec_review_result_path` / 两个白名单），
  故 helper MUST 落 `prompt_builder.py` 并由 `result_gate` 导入；反向必成环（见 D1 落位方向条）。
- [D3 与既有 `_impl_diagnosis_section` 重复渲染] → 已写入 D3 的「零重复约束」与 task 2.1；
  实现时若发现**同一诊断字段被两段各自作为独立条目渲染**，即为本约束被违反；判据是字段级——
  `error` 原文内含 `attribution` 子串系两字段同源（均取自 `final_error`），不计为重复（见 D3 字段级判据）。
- [归因文案与既有 `_classify_terminal_no_commit` 文案冲突] → 既有方法无特征时返回「未提交即收工」
  （`runner.py:1193/1198`，`tests/test_terminal_nocommit_gate.py:196/203` 断言），本 SPEC 要求
  「未收工即停」。实现 MUST 以新增映射层产出新文案，MUST NOT 改既有方法返回值（见 task 4.1）。

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
