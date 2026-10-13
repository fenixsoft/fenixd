# 验证报告：add-dsh-adapter-integration

> ⚠️ 本报告由框架于 2026-10-13T13:24:29Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-13T13:13:03.848795+00:00+run-result@mtime1791897836306479929

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 11/14 场景通过，3 失败，0 错误（2 个真实产品 Bug）**

14 场景 11 过 3 败，归并 2 个产品 Bug：① build_env 覆写键回灌（major，dsh-spawn-contract 与 dsh-adapter-unit-tests-green 同根因）；② error 事件投影丢错误码（minor）。无新增 env/test-defect/flaky 豁免（unit-tests 场景级 env 分类为跨轮指令沿用，根因实归 bug①）。

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 3 |
| 错误 | 0 |
| 产品 Bug | 2 |
| 本链增量 Token（输入） | 11.60M |
| 本链增量 Token（输出） | 0.21M |


## 真实产品 Bug

### BUG-01（severity=major）· json_output/checks.env_no_anthropic

- 关联场景：dsh-spawn-contract、dsh-adapter-unit-tests-green
- 描述：DshAdapter.build_env 防串扰剔除对 env_overrides 失效：覆写键 ANTHROPIC_AUTH_TOKEN/ANTHROPIC_MODEL 直通 dsh 子进程环境。守卫仅认 consumed=(BASE_URL,API_KEY) 与 ambient 求值的 banned 集，daemon 环境无这些键时覆写键原样回灌，违反场景契约「env 无 ANTHROPIC_* 残留」。dsh-adapter-unit-tests-green 场景级 env 分类系跨轮指令沿用；其单测失败与 spawn-contract 同根因（上轮本机复现 PASS 系 shell ambient ANTHROPIC_MODEL 恰被前缀剔除遮蔽了回灌路径；实测主树 main@1d82f7d5 文件与 HEAD 一致，不存在代码代差）
- 根因：dsh_adapter.py build_env：env_overrides 再注入守卫按「覆写键是否出现在 ambient banned 清单」判断，而非按覆写键自身匹配 DSH_BANNED_ENV_PREFIXES/DSH_BANNED_ENV_EXACT_KEYS，ambient 缺键的 ANTHROPIC_*/CLAUDE_* 覆写键漏剔
- 证据（场景 dsh-spawn-contract 结构化证据，引用）：
  - failed_assertions: [{"type": "exit_code", "selector": "exit_code", "expected": "0", "actual": "1"}, {"type": "json_output", "selector": "ok", "expected": "true", "actual": "false"}, {"type": "json_output", "selector": "checks.env_no_anthropic", "expected": "true", "actual": "false"}]
  - screenshots: []
  - first_failed_step: 步骤1 spawn-probe：checks.env_no_anthropic=false——build_spawn_spec 后 spec.env 残留 ANTHROPIC_* 覆写键（其余 9 项检查全过）

### BUG-02（severity=minor）· json_output/checks.form_b_code_kept

- 关联场景：dsh-projection-failure-semantics
- 描述：error 事件（无 final）投影丢弃 dsh 错误码：_project_error 仅渲染 message，同文件 turn_end 错误路径渲染「dsh: {code}: {message}」供 translate_dsh_error_text 归因，error 形态失败（如 TRANSPORT）投影后失去 circuit 归因码，双路径不对称；终态可判性两形态均达标
- 根因：_project_error 未提取 entry.error.code 拼入渲染串，与 _project_status 错误分支的 code 渲染口径不一致
- 证据（场景 dsh-projection-failure-semantics 结构化证据，引用）：
  - failed_assertions: [{"type": "exit_code", "selector": "exit_code", "expected": "0", "actual": "1"}, {"type": "json_output", "selector": "ok", "expected": "true", "actual": "false"}, {"type": "step_error", "selector": "checks.form_b_code_kept", "expected": "error 事件投影保留 TRANSPORT 错误码", "actual": "false——投影 error 行仅含 message conn refused"}]
  - screenshots: []
  - first_failed_step: 步骤1 failure-probe：checks.form_b_code_kept=false——error 事件（无 final）投影后 TRANSPORT 错误码未保留（form_a 同断言通过）


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dsh-spawn-contract | DshAdapter.build_spawn_spec 生成契约探针：argv 含 dsh headless --json、resume 时带 --session-id fenix- 命名空间 id、prompt 全文经 stdin_payload、cwd=worktree、env 无 ANTHROPIC_* 残留（dsh banned env 扩充集生效）、Bundle 模型配置显式渲染含 model/baseURL/apiKey（不依赖 dsh 默认档）。出处 spec/changes/add-dsh-adapter-integration/specs/dsh-harness-integration/spec.md「DshAdapter spawn 契约」；接口源 core/agent_runner/harness/protocol.py:45-120（SpawnRequest/SpawnSpec） | failed（已修正） | 3/8 | product-bug |
| dsh-capabilities-process-patterns | DshAdapter.capabilities()/process_patterns() 探针：进程识别 patterns 非空、能力对账卡字段齐备且可 json.dumps 序列化，task_tools/resume 按探针结论（resume 支持、批内并行降级串行）、max_turns_enforcement=daemon-side。出处 tasks.md 1.2；结构源 core/agent_runner/harness/protocol.py:122-156（HarnessCapabilities）；能力结论源 dsh-bundle/docs/probe-findings.md 第四节 | pass | 0/6 | - |
| dsh-stderr-classification | dsh stderr 错误码表分类探针：DshAdapter.classify_stderr 对 SPEC-2 探针错误码（MISSING_CREDENTIAL/UNKNOWN_MODEL/RATE_LIMIT/HTTP_429/SERVER/HTTP_5xx/TIMEOUT/AUTH/HTTP_401/TRANSPORT 及 startup failed 汇总块）映射到现有分类枚举（missing_credential/unrecognized_model/ratelimit/transient/auth_error）；空行→generic。熔断/瞬断/记账治理零改动由既有 provider_circuit 回归场景覆盖。出处 spec.md「stderr 分类接口化」；错误码表源 dsh-bundle/docs/probe-findings.md 第二节；现状枚举源 core/agent_runner/harness/protocol.py:153-155 | pass | 0/7 | - |
| dsh-prompt-harness-notes | prompt harness 注记参数化探针：claude 通道组装结果与改造前快照逐字节一致（快照黄金文件对账）；同车道 claude/dsh 两版 prompt 差异全部落在 harness_notes 段；Task 工具族（TaskCreate/TaskUpdate）契约段一字不改；agents/implementer.md 长任务等待节以 {harness_notes} 占位符承载。出处 spec.md「prompt harness 注记参数化」；现状段源 core/agent_runner/prompt_builder.py:787（_noninteractive_contract_section） | pass | 0/6 | - |
| claude-channel-zero-regression | claude 通道行为零变化回归：原样运行既有快照与分类测试（test_harness_claude_snapshot.py 黄金快照、test_provider_circuit.py 分类/熔断、test_harness_adapter.py adapter 契约）全绿，证明 claude 实现系现有文本模式平移。出处 spec.md「stderr 分类接口化」claude 快照 scenario 与 design.md Goals「claude 通道行为零变化」 | pass | 0/5 | - |
| reader-side-tests-green | 读侧现有测试原样复用全绿：test_task_track.py、test_liveness_hang_discrimination.py、test_agent_runner_gate.py（result_gate 读侧）在投影层落地后不经修改全部通过——投影正确性的证据=读侧测试全绿。出处 spec.md「事件投影到 canon 形状」MUST 条款 | pass | 0/5 | - |
| dsh-projection-fixtures-replay | fixtures 回放投影契约探针：以 dsh-bundle/tests/fixtures/headless-events.jsonl 为契约源逐事件经 normalize_event 投影写入临时 run jsonl——session→init（session_id+tools）、tool_call{callId,tool,input}→{id,name,input}、tool_result{callId,status,result}→user block（status=error 映射 is_error）、text→assistant text block、final→result（output/num_turns/session_id/usage 形状）、num_turns 由 turn_end 计数、usage 由 step_end 累计（128x2/32x2）；再以 core/run_task_track 解析出 1 基 taskId 进度、liveness/result_gate 读侧不受影响。出处 spec.md「fixtures 回放接通成对契约」；字段映射修正源 dsh-bundle/docs/probe-findings.md 第五节 | pass | 0/9 | - |
| dsh-projection-robustness | 投影层防御路径探针：truncated 标记透传不丢；未知事件类型忽略+计数且不中断流（后续事件照常投影）；坏 JSON 行归入解析失败统计不炸管道；空流零投影不异常；可观测性计数（各类型收到/投影/忽略、坏事件三类：JSON 解析失败/未知类型/超限截断）落结构化日志。出处 spec.md「新采集链路可观测性」与 design.md 风险表「投影遗漏事件类型」「截断事件破坏 JSON 解析」 | pass | 0/7 | - |
| dsh-projection-failure-semantics | 失败语义可终判探针：形态一「exit 1 + turn_end(reason.kind=error)」与形态二「error 事件且无 final」两条流分别投影后，run jsonl 末行均为 RUN_TERMINAL_EVENT_TYPES 可判定终态（core/event_bus.py），错误 code 保留供 circuit 归因，不产生悬挂在飞。出处 spec.md「失败语义可终判」；dsh 失败形态源 dsh-bundle/docs/probe-findings.md 第一/二节 | failed（已修正） | 2/6 | product-bug |
| dsh-session-namespace-resume | session 绑定与续跑探针：resume 经 --session-id 传入（build_spawn_spec argv 相邻对）；跨 provider resume 禁令保持（SessionTracker._resumable_session_id provider 不符→None）；fenix-<run_id> 命名空间在 session/runner 侧有构造点且 dsh 全链产出的 session id 落在该命名空间。出处 spec.md「session 绑定与续跑」；design.md 决策 3；现状禁令源 core/agent_runner/session.py:31-50 | pass | 0/6 | - |
| dsh-usage-extraction | usage 提取与降级标记探针：可得路径（探针结论=dsh step_end 携带 usage，final 不带）——逐 step_end 累计出 inputTokens/outputTokens/totalTokens 且 usage_source=available；不可得路径（无 step_end 流）——usage 零值+usage_source=unavailable 显式降级标记，MUST NOT 伪造数值。出处 spec.md「usage 降级标记」；探针结论源 dsh-bundle/docs/probe-findings.md 第三节 | pass | 0/6 | - |
| dsh-health-check-failfast | 健康检查与工厂注册探针：工厂 resolve_adapter(dsh) 不再抛 HarnessNotDeployedError（返回 DshAdapter）；版本白名单含钉版 0.2.0-rc.2（dsh-bundle README 版本兼容表）；PATH 无 dsh 时健康检查 fail-fast 且错误信息含「版本」与修复指引；伪造 dsh 报告低版本（0.2.0-rc.1）同样 fail-fast；健康检查通过后 resolve_adapter_from_config(agent.harness=dsh) 全链拿到 DshAdapter 不静默回退 claude。出处 spec.md「健康检查与工厂注册」；现状 fail-fast 源 core/agent_runner/harness/__init__.py:105-117 | pass | 0/7 | - |
| dsh-adapter-unit-tests-green | 交付物自带单测全绿：tests/test_harness_dsh_adapter.py（spawn 契约快照/stderr 分类/session/usage/健康检查/prompt 快照）与 tests/test_dsh_projection.py（fixtures 回放/失败语义/可观测性）作为 tasks.md 声明的新增交付测试文件存在且 pytest 全过。出处 tasks.md 交付物清单与 1.4/2.3/2.4/3.2/4.3/5.2/6.3 | fail | 1/2 | env |
| dsh-e2e-dispatch-chain | 端到端全链冒烟（环境依赖；有 fallback: bundle 依赖优先取验证树 dsh-bundle/node_modules，缺则经 git worktree list 定位主树同名 bundle 软链复用，再缺则 npm ci 现装）：真机 dsh 0.2.0-rc.2 + DSH_HOME 隔离 profile 挂载 fenix-dsh-bundle（link: 软链装）+ mock-model-server.mjs 假模型端点（脚本化 text/TaskCreate 工具调用步，预留会话标题牺牲步）下，agent.harness=dsh 经 AgentRunner 真实 _run_agent spawn dsh 进程：健康检查就绪路径通过（含 Bundle 挂载探测）、run jsonl 收到归一化事件（init/assistant/tool_use/user/result）、run_task_track 解析出 1 基 taskId 进度、终态收口不悬挂、原始 dsh 事件 dump 旁路文件存在、run_metrics 结构化日志含投影计数与 usage_source=available、假模型端点请求日志实证 model=显式配置值（Bundle 配置显式渲染到真实传输层）。出处 tasks.md 7.1；spec.md「就绪后全链走 dsh」「可观测性三件套随首个采集交付」；装置源 dsh-bundle/README.md 安装节与 tests/fixtures/mock-model-server.mjs | pass | 0/10 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| dsh-adapter-unit-tests-green | exit_code exit_code | env | 环境因素（非产品缺陷） | 验证执行区代码代差（env 判定）：当前实现 dsh_banned_env_keys 含 ANTHROPIC_/CLAUDE_ 前缀剔除（agent_env_keys.py:28）且 build_env 先剔后透传（dsh_adapter.py:674-685），本机复现 PASS；验证 run 与 merge-... |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

