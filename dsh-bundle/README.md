# fenix-dsh-bundle

fenixd 的 dsh 通道 Bundle：把 ADR-269 门禁体系（Task 工具族、三守卫、非交互审批、模型显式配置、
AGENTS.md 约定载体）接入 [dsh](https://www.npmjs.com/package/@deepseek-ai/dsh)（DeepSeek Harness）。
本 Bundle 供 **headless 车道**专用——fenixd 以无人值守 `dsh headless` 派发实现工作。

探针结论与母设计投影表修正建议见 [docs/probe-findings.md](docs/probe-findings.md)。

## 版本兼容表

| Bundle 版本 | dsh 运行时 | 说明 |
| --- | --- | --- |
| 0.1.0 | **0.2.0-rc.2**（唯一钉版） | peerDependencies 精确钉 `@deepseek-ai/dsh`、`@deepseek-ai/dsh-app-boot`、`@deepseek-ai/dsh-tools` 为 `0.2.0-rc.2`，`@deepseek-ai/cordis` `~4.0.4` |

版本不符时 dsh 以 `evaluatePluginCompatibility` 校验 peer 并**跳过本 Bundle**（stderr 显式版本错误，
不静默降级）；随后因显式模型配置未应用，headless 车道将以 `MISSING_CREDENTIAL` 退出（见已知限制 3）。
升级 dsh 运行时必须同步升版 Bundle 并重测（`npm install` + 全量冒烟）。

## 组件

| 组件 | 入口 | 作用 |
| --- | --- | --- |
| Task 工具族 | `src/taskTools.ts` | `TaskCreate/TaskUpdate/TaskGet/TaskList`，会话内 1 基 taskId、`pending→in_progress→completed` 状态流转、metadata，等价 claude Task 工具语义 |
| 三守卫 | `src/guards.ts` | 挂 `tools/pre-execute`（先于审批）：主树写拦截（`FENIX_RUN_PROJECT_ROOT`/`FENIX_RUN_WORKTREE`）、读图拦截、场景批处理（骨架放行/带肉拦截），语义对齐 `.fenix/hooks/*.py` |
| 非交互审批 | `src/approval.ts` + `cordis.patch.yml` | `sandbox-policy.mode=danger-full-access` + `approval.policy=never`（等价 claude `--permission-mode bypassPermissions`）；策略非 never 时启动期拒绝 |
| 模型显式配置 | `src/modelConfig.ts` | 三要素 `provider/baseURL/apiKeyEnv/model` 缺一即拒绝启动（「模型未显式配置…绝不回退 dsh 默认档」），渲染进 `llm-pi-ai` providers 与 `agent-default-model`；版本钉扎同在此 fail-fast |
| 约定载体 | `cordis.patch.yml` | `headless-runner`（required 启动条目）追加注入 `fenixModelConfig`，构成模型缺失/版本不符的 StartupError exit 1 致命链 |

## 安装 / 卸载

Bundle 依赖解析按**软链安装**口径（`file:` 拷贝装会使副本失去 `node_modules`、peer 断链，见
probe-findings 第六节）：

```bash
# 1) 在 Bundle 目录装依赖（npm 自动安装精确版 peer）
cd <repo>/dsh-bundle && npm install

# 2) 以 link: 形态挂入自定义 profile（DSH_HOME 隔离示例）
export DSH_HOME=/path/to/isolated-home
dsh --profile fenix --from-default-profile headless   # 首次创建 profile
DSH_HOME=$DSH_HOME dsh plugin --profile fenix add "link:<repo>/dsh-bundle"
# 并在 $DSH_HOME/profiles/fenix/package.json 的 dsh.profile.bundles 里追加 "fenix-dsh-bundle"

# 3) 验证
DSH_HOME=$DSH_HOME dsh --profile fenix --dump-config | grep fenix   # 可见三条 insert 与各覆盖条目

# 卸载
DSH_HOME=$DSH_HOME dsh plugin --profile fenix remove fenix-dsh-bundle
```

部署侧还需以 `--patch` 提供模型三要素（示例）：

```yaml
- id: fenix-model-config
  config:
    model:
      provider: fenix-gateway        # 路由名（任取）
      baseURL: http://127.0.0.1:18787/v1
      apiKeyEnv: FENIX_LLM_API_KEY   # 从该环境变量读 key
      model: glm-5.3-flash
```

### 模型配置 schema 与渲染说明

`fenix-model-config` 插件的 config 只有一个 `model` 段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `provider` | ✓ | 路由名，渲染为 `llm-pi-ai.providers` 的键与 `agent-default-model.provider` |
| `baseURL` | ✓ | OpenAI 兼容端点（`api` 固定 `openai-completions`） |
| `apiKeyEnv` | ✓ | 凭据环境变量名（运行时须已导出，否则 `MISSING_CREDENTIAL`） |
| `model` | ✓ | 模型 id，渲染为 providers models 目录唯一条目与 `agent-default-model.model` |
| `contextWindow` / `maxTokens` | — | 缺省 262144 / 32768 |
| `headers` | — | 附加请求头（键值对） |

渲染是单向的：Bundle patch 以 `!!js ctx.fenixModelConfig.*` 惰性表达式把该服务铺进 dsh 的
`llm-pi-ai`（providers 整体替换，无默认档残留）与 `agent-default-model`。改模型只改这一处。

## ADR-269 门禁载体的 dsh 变体说明

ADR-269 裁定「门禁与项目约定走入库 CLAUDE.md」。claude 通道原生读 CLAUDE.md；dsh 通道原生读
**AGENTS.md**（`dsh-agent-instructions`，以 durable user 消息注入 `<system-reminder>…Instructions
from: AGENTS.md…</system-reminder>`，同内容去重）。变体落地：

- **机制**：仓库根 `AGENTS.md` 为**实体文件**，内容与 `CLAUDE.md` 逐字节一致（sha256 全等）。
  不以软链落地的原因：fenixd 交付物守卫 `worktree_manager/queries.py file_exists_on_branch`
  判 symlink（git mode 120000）非落地交付物，软链形态会被确定性打回。claude 通道读 CLAUDE.md、
  dsh 通道读 AGENTS.md，两通道内容等价；
- **实测**：实体文件下 DSH_HOME 隔离会话注入消息含完整 CLAUDE.md 正文且仅一条（去重生效）；
  软链形态此前亦经真机实测注入等价（dsh 按路径读文件，两形态装载行为一致）；
- **局限**：
  - 双拷贝漂移：AGENTS.md 与 CLAUDE.md 是两份独立文件，无软链的单一真相源保证——修订项目
    约定时 MUST 同步两处（交付物守卫约束下的取舍，单通道场景以 CLAUDE.md 为权威源）；
  - dsh 的指令注入是「参考性 guidance」措辞（`may be relevant… do not override`），与 claude 的
    项目指令强度不同，依赖强约束的规则仍应以工具面（三守卫）兜底而非提示词。

## 测试

```bash
cd dsh-bundle && npm install && npx vitest run   # 76 例单测（dsh 以 alias 桩解耦）
```

端到端冒烟（DSH_HOME 隔离 + 假模型端点）：

```bash
node tests/fixtures/mock-model-server.mjs --port 18787 --script <steps.json> --log <req.jsonl> &
FENIX_MOCK_KEY=sk-mock FENIX_RUN_WORKTREE=<wt> FENIX_RUN_PROJECT_ROOT=<root> \
  DSH_HOME=<home> dsh --profile fenix --patch <model-patch.yml> headless --json "<task>"
```

mock 步骤协议（`tests/fixtures/mock-model-server.mjs` 头注）：`{"kind":"tool_calls","toolCalls":[{"name":"TaskCreate","arguments":{…}}]}`；
注意 `toolCalls` 为驼峰字段。headless 首轮回合间**会话标题生成器会额外消费一步**，脚本编排需预留牺牲步。

## 已知限制

1. **批内并行判定**：dsh 原生 subagent 在父事件流中无嵌套事件（只有最终文本），无法对齐 claude 的
   批内并行事件形状——fenixd 语义在 dsh 通道降级为串行调用。
2. **usage**：`status(step_end)` 携带逐条 usage，`final` 不带；累计需消费方求和（探针结论：
   `usage_source: available`，无降级路径）。
3. **版本不符残余边缘**：peer 不符 → dsh 跳过 Bundle（stderr 显式版本错误）→ 显式配置不应用。
   宿主无默认档凭据时以 `MISSING_CREDENTIAL` exit 1（fail-fast，实测）；宿主存在默认档凭据时
   dsh 会带警告继续跑默认路由——Bundle 被跳过时连同 patch 一起失效，无法在 Bundle 内拦截，
   由 fenixd 派发层保证凭据卫生（不导出默认档 key）。
4. **会话内状态**：Task 工具族状态表在进程内存（会话内一致）；dsh 会话 resume 不恢复任务表。
5. **`--json` 投影截断**：单字符串 8 KiB / 整行 32 KiB 截断 + `truncated: true`（仅投影层，执行层
   完整）；消费方必须检查该标志。
6. **技能目录**：dsh 不扫 `.claude/skills`（根为 `$DSH_HOME/skills`、`~/.agents/skills`、项目
   `.dsh/skills`/`.agents/skills` 与 `customSkillDirs` 配置）；fenixd 技能需软链桥接，本 Bundle 不代劳。
7. **构建脚本**：以依赖树整体安装时 pnpm 可能拦截原生模块构建脚本（`node-pty`/`koffi` 等）；
   headless 车道不依赖这些原生件，按 `ignoredBuiltDependencies` 声明跳过即可。
