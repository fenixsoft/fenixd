# fenix-dsh-bundle 真机探针结论（dsh 0.2.0-rc.2）

探针方法：`DSH_HOME` 隔离目录 + `tests/fixtures/mock-model-server.mjs`（OpenAI 兼容假模型端点，
响应序列可脚本化）驱动 `dsh headless --json`；错误路径以脚本化 HTTP 错误步与真实凭据缺失复现。
原始证据：`.dsh-test/errcase-*`（错误码）、`.dsh-test/probe-events.jsonl` / `probe-truncate.jsonl`（事件流与截断）、
`tests/fixtures/headless-events.jsonl`（全事件类型样本）。本文件只沉淀结论与修正建议。

## 一、headless `--json` 事件流

实测事件类型全集（样本见 `tests/fixtures/headless-events.jsonl`）：

| type | 关键字段 | 备注 |
| --- | --- | --- |
| `session` | `sessionId`、`cwd` | 首事件 |
| `status` | `phase: turn_start / step_start / step_end / turn_end` | `step_end` 携带 `usage`；`turn_end.reason.kind` 为 `completed` 或 `error`（error 带 `error{message,code,status?}`） |
| `text` | `text` | assistant 文本增量为整段下发 |
| `thinking` | — | 模型思考（本探针 mock 未触发） |
| `tool_call` | `callId`、`tool`、`input` | `tool` 即工具名，`input` 为模型参数对象 |
| `tool_result` | `callId`、`status: completed\|error`、`result` | 拦截/失败同样物化为 `status:"error"` 的事件 |
| `final` | `text` | 收尾文本，不截断 |

截断边界实测（`probe-truncate.jsonl`）：

- **单字符串值投影上限 8 KiB（UTF-8）**：18000 字节的 `tool_call.input` 投影为 8245 字节（含 JSON
  结构开销）且事件级 `truncated: true`；**执行层不受影响**，工具收到完整 18000 字节并完整落盘。
- **整行上限 32 KiB**（源码 `boundJsonLine`）：一行内多字段合计超限同样截断。
- `final.text` 不截断。
- 结论：截断只发生在**投影层**（headless 事件序列化），不是执行层语义；消费方解析 `--json` 输出
  时必须容忍 `truncated: true` 与不完整 JSON 值。

## 二、stderr 错误码与 provider_circuit 映射

形态：headless 失败时 stderr 输出 `dsh: <code>: <message>`，进程 exit 1（ StartupError 场景为
`dsh: startup failed: …` 汇总块 + 完整诊断日志路径）。

实测错误码（原始证据 `.dsh-test/errcase-*`）：

| 触发 | dsh 错误码 | 消息样例（截引） |
| --- | --- | --- |
| apiKeyEnv 未设置 | `MISSING_CREDENTIAL` | `no credential for provider route "fenix-mock"; its profile resolves FENIX_MOCK_KEY, which is not set…` |
| 模型名不在 providers 目录 | `UNKNOWN_MODEL` | `pi-ai provider "fenix-mock" has no configured model "no-such-model"` |
| HTTP 401 / 404 / 429 / 500 / 连接拒绝（自定义 OpenAI 兼容端点） | `TRANSPORT` | `Connection error.` |

**重要结论：pi-ai 的 `openai-completions` 路由把端点 HTTP 错误一律粗化为 `TRANSPORT: Connection error.`**，
不区分 401/429/500/连接拒绝；官方 deepseek 路由才有 `AUTH` / `QUOTA` / `RATE_LIMIT` / `SERVER` /
`HTTP_<status>` 细分（`dsh-llm` 默认重试码 `[EMPTY_RESPONSE, RATE_LIMIT, SERVER, TIMEOUT, TRANSPORT]`）。

→ fenixd provider_circuit 分类建议：

| dsh 错误码 | fenixd 分类 | 说明 |
| --- | --- | --- |
| `MISSING_CREDENTIAL` | `missing_credential`（配置缺失，不入 circuit） | 修复=补环境变量/凭据，重试无意义 |
| `UNKNOWN_MODEL` | `unrecognized_model` | 模型名/目录配置错误 |
| `RATE_LIMIT` / `HTTP_429` | `ratelimit` | 可退避重试 |
| `SERVER` / `HTTP_5xx` / `TIMEOUT` | `transient` | 可退避重试 |
| `AUTH` / `INVALID_CREDENTIAL` / `HTTP_401` | `auth_error` | 不入重试 |
| `NO_ADAPTER` / `TRANSPORT`（官方路由） | `transient`（连接类）/ 按消息细分 | 官方路由下 TRANSPORT 为连接/网络类 |
| `TRANSPORT`（**自定义 OpenAI 兼容端点**） | **不可细分**，建议保守归 `transient` 并以消息/状态旁路取证 | 粗化是路由实现行为，Bundle 侧无法恢复细分 |

注意 `TRANSPORT: Connection error.` 同时也是重试耗尽后的最终形态——dsh-llm 对 TRANSPORT 默认
自动重试，收到该错误意味着重试已用尽。

## 三、usage 形态

**可得，无降级路径。** `status step_end` 事件携带 `usage: {inputTokens, outputTokens, totalTokens}`
（每步一条，实测 mock 恒回 128/32/160 忠实透传）。`final` 事件不携带 usage，累计值需消费方对
step_end 求和（或走 `dsh-session-stats` 服务，Bundle 场景不需要）。`usage_source: available`。

## 四、原生能力盘点（复用 vs 自研判定）

| 原生件 | 实测/源码结论 | 判定 |
| --- | --- | --- |
| `dsh-tool-todo`（`todo_write`） | 无任务 id、整表替换语义，与 claude Task 工具族（1 基 taskId、单条状态流转、metadata）不兼容 | **自研**（Bundle 的 TaskCreate/TaskUpdate/TaskGet/TaskList） |
| `dsh-tool-subagent` / `subagent` 事件 | 父事件流**无嵌套事件**，子代理只以最终 assistant 文本回到父流 | claude 的批内并行/嵌套事件形状**不可对齐** → fenixd 语义降级为串行调用，不在本 Bundle 范围内模拟 |
| `dsh-skill` | 技能根目录：`$DSH_HOME/skills`、`~/.agents/skills`（或 `$DSH_AGENTS_HOME`）、`<project>/.dsh/skills`、`<project>/.agents/skills`、`customSkillDirs` 配置。**不扫 `.claude/skills`**（实测 wechat-claude-code 技能源自 `~/.agents/skills/`，非 `.claude`） | fenixd 技能如需暴露给 dsh，需在 `.agents/skills` 建桥接（软链农场）或配 `customSkillDirs`；本 Bundle 不做 |
| `dsh-hooks-claude-code` | 能消费 claude hooks schema 的适配层存在（监听同一 `tools/pre-execute` 面），但它面向「把 claude hooks 接进 dsh」的通用桥，三守卫需要 fenixd 专属 env（FENIX_RUN_WORKTREE/PROJECT_ROOT）与精确错误文案 | **自研**（Bundle 内 `guards.ts` 直接挂 `tools/pre-execute`，语义与 `.fenix/hooks/*.py` 一一对齐；适配桥反而引入 schema 翻译损耗） |
| `dsh-agent-instructions`（system-prompt 分区） | **原生读 `AGENTS.md`**（同内容去重），以 durable user 消息注入：`<system-reminder>…Instructions from: AGENTS.md…</system-reminder>`。实测软链 AGENTS.md→CLAUDE.md 后正文完整注入且只注入一条 | **复用原生**（仓库根建 AGENTS.md 软链即达，见 README 的 ADR-269 dsh 变体说明） |

工具注册面补充：注册后模型可见工具表带 `TaskCreate/TaskGet/TaskList/TaskUpdate` + 24 个原生工具
（`bash, create_goal, edit, exit_plan_mode, get_goal, glob, grep, interrupt_agent, job_kill, job_list,
job_output, list_agents, read, read_image, send_message, skill, subagent, subagent_fork, todo_write,
update_goal, web_fetch, web_search, workflow, write`）。

## 五、对母设计 §4.3 投影表的修正建议

1. **tool_call 字段映射**：dsh 为 `{callId, tool, input}` → claude 形状 `{id, name, input}`；
   `tool_result` 为 `{callId, status, result}` → `{id/use, content}`，`status:"error"` 对应 claude 的
   `is_error`。投影层应按此改名，而不是透传 dsh 字段名。
2. **usage 位置**：usage 在 `status(step_end)` 上，**不在** `final` 上；投影表若把 usage 挂在 final
   需改为「逐 step_end 累计」。
3. **截断警示**：`--json` 投影对单字符串 8 KiB / 整行 32 KiB 截断并打 `truncated: true`；投影层
   消费方（fenixd 解析器）必须检查该标志，禁止假设事件完整。执行层不受影响。
4. **turn_end.error 形状**：失败收尾为 `reason: {kind: "error", error: {message, code, status?}}`，
   投影为 claude 的 error result 时应保留 code（可直映 provider_circuit，见第二节）。
5. **文本事件粒度**：`text` 为整段下发（非逐 token 增量），投影层无需做增量拼接状态机。

## 六、Bundle 集成期新发现（2.1/2.2/5.3 落地实测）

装配链验证结论（全部真机复现）：

1. **Bundle 安装形态决定依赖解析**：`dsh plugin --profile <n> add file:<path>` 是**拷贝**装（副本无
   node_modules → peer `@deepseek-ai/*` 断链 → 三插件全部 failed to import）；`link:<path>` 是**软链**装
   （解析回到真实目录的 node_modules）。Bundle 以软链形态安装时，`dsh-bundle/node_modules` 由
   `npm install`（自动装 peer，精确 0.2.0-rc.2）供给。README 安装命令按 `link:` 口径书写。
2. **peer 依赖即版本钉扎契约**：dsh 启动时以 `evaluatePluginCompatibility` 对照 peerDependencies 与
   运行时版本，不符则**跳过该 bundle**并 stderr 显式版本错误（`skipping profile bundle … incompatible
   with dsh 0.2.0-rc.2 …`）。实测 peer 改 9.9.9 → bundle 跳过 → 显式配置未应用 → 无默认档凭据 →
   `MISSING_CREDENTIAL` exit 1（不静默降级）。残余边缘：宿主存在默认档凭据时会以 stderr 警告
   继续跑默认路由——需 fenixd 派发层凭据卫生保证，Bundle 侧无法拦截（跳过的 bundle 连同它的
   patch 一起失效，bundle 内代码无法参与该场景）。
3. **模型缺失 fail-fast 链**：`cordis.patch.yml` 给 required 启动条目 `headless-runner` 追加注入
   `fenixModelConfig` → `assertModelExplicit` 抛「模型未显式配置」→ headless-runner 无法激活 →
   `StartupError: 1 required plugin did not activate` exit 1。实测 stderr 含完整三要素提示与
   「绝不回退 dsh 默认档」措辞。
4. **cordis 插件纪律**：访问 `ctx.tools` 必须声明 `inject: ["tools"]`（否则 `cannot get property
   "tools" without inject`，插件不激活但非 required 条目时仅警告）；参数 schema 的 `type:"object"`
   属性必须显式 `additionalProperties: true|false`（dsh-tools 的 JsonSchemaError 拒绝隐式）；
   `defineTool` 会真实编译/校验 schema（非恒等包装）。
5. **配置渲染链**：`!!js ctx.fenixModelConfig.*` 惰性表达式在 patch 应用期以注入服务求值，
   `--patch` 覆盖 `fenix-model-config` 的 `config.model` 三要素后，providers/默认模型全部由该服务
   渲染——单一来源实测成立（mock 端点收到 `model: mock-model` + `Bearer sk-mock`）。
6. **审批面**：`sandbox-policy.mode=danger-full-access` + `approval.policy=never` 生效下，守卫 deny
   先于审批：主树写被 `tools/pre-execute` 拦下并以 `Error: 写主树被拦截…主树只读…` 的工具错误
   结果回模型，全程零交互等待。
7. **编排噪音**：headless 首轮回合间，会话标题生成器（`dsh-session-title-first-prompt-llm`）会向
   模型端点额外发一个请求——脚本化探针须预留牺牲步，否则步骤游标错位。
8. **AGENTS.md 装载**（详见第四节）：软链方案实测成立，注入消息标记 `Instructions from: AGENTS.md`，
   同内容去重后单条注入。
9. **system-prompt 分区 API**（验证打回第 1 轮补实测）：`@deepseek-ai/dsh-system-prompt` 暴露
   `ctx.systemPrompt.section({ name, order, text })`（`text` 支持 `(context) => string` 每次
   assembly 求值；空串 section 被 `renderPrompt` 丢弃），官方用例见
   `dsh-file-reference-local`（`ctx.inject(["systemPrompt"], …)` + `getSectionOrder("FILE_REFERENCE")`）。
   Bundle 据此落 `fenix:agents-md` 分区（src/agentsMd.ts）：假模型端点捕获请求体实证
   `body.system` 含 AGENTS.md 正文与标记——原生 `dsh-agent-instructions` 只以 durable user
   消息注入、不进 system 字段，两者互补不重复计费同一字段。
10. **pnpm 12 strict-dep-builds**（验证打回第 1 轮补实测）：pnpm 12.11.2 对依赖树中被拦截的
   构建脚本（esbuild/node-pty/koffi 等 6 个），在用户未表态时**硬报错**
   `ERR_PNPM_IGNORED_BUILDS`，`--ignore-scripts` 回退也无效；package.json 的 `pnpm.*` 字段
   已不被读取（WARN 明示）。有效出路：包目录 `pnpm-workspace.yaml` 声明
   `strictDepBuilds: false`（恢复警告不阻断）+ `ignoredBuiltDependencies` 显式列知情忽略
   清单。Bundle 测试面不消费任何原生构建产物（esbuild 平台二进制走 optionalDependencies），
   忽略清单语义安全。
