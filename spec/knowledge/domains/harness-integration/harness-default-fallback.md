# harness 默认档对称回落

<!-- knowledge: capability=harness-default-fallback rev=2
     sources=spec/changes/add-harness-default-key-fallback,spec/changes/add-dispatch-precheck-true-fallback -->

无 `agents.models` 分配的 Agent 按 harness 自身配置开箱启动的对称回落契约：回落合法且 fenixd/Bundle 两侧贯通、笔误仍拦截、回落可观测（两层 WARN 留痕 + metrics 归因标记），claude 与 dsh 两通道语义对齐。

## 规则

- **对称回落语义**：`SpawnRequest` 无 provider 链分配时，车道按各 harness 自身配置启动，MUST NOT 以预检错误拒绝 spawn——claude 适配器走环境继承 + CLI 默认档；dsh 适配器省略 `--patch`（不写 patch 文件、argv 不携带该参数），由 dsh 按 profile 自身配置的默认模型启动，`build_env` 不桥接 `FENIX_DSH_PROVIDER_API_KEY`。dsh 侧「无 patch = profile 默认档」是回落通道的原生语义，禁以写空 patch 表达回落。Bundle 侧（fenix profile 的 modelConfig 插件）兑现同语义：`config.model` 整体缺席（无 patch 回落形态）时 MUST NOT 抛「模型未显式配置」StartupError，`agentDefaultModel`/`fenixModelConfig` 服务交由 dsh 自身默认模型解析链（dsh-base 通道）供数并跳过显式覆盖；`headless-runner` 等依赖这些服务的 required 插件正常激活——无分配 spawn 进程存活并执行任务是回落实际可达的验收锚点。
- **回落与配置笔误的划界**：回落判定以 `env_overrides` 的 provider 链键存在性为准——完全无链键（baseurl/apikey 均空）即回落形态；含任一链键但三要素不全（仅 baseurl、仅 apikey、baseurl+apikey 缺 model）属配置笔误，仍 MUST 抛 `DshSpawnConfigError`。`req.model` 不参与回落判定（无分配车道传钉死模型名仍是回落形态）；链键值为空白串视为空；非链的自定义 env_overrides 照常透传。Bundle 侧同构划界：判定基准是「`config.model` 键整体缺席」而非「值为空」——键不存在/无 config 为回落形态；`config.model` 为 null、空串、非对象或在场但要素（model/baseURL/apiKeyEnv）任一缺失为部分配置，仍 fail-fast（笔误防护）。
- **显式链形态不受回落语义改写**：显式全链 spawn 产物为 argv 含 `--patch` 且 patch 文件落盘渲染 model/baseURL 三要素、env 桥接 `FENIX_DSH_PROVIDER_API_KEY`、`ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY` 两 consumed 键不透传子进程——该形态逐字节恒定，是回落语义的回归红线（两侧皆然：adapter spawn 装配与 bundle modelConfig 显式链校验路径均保持既有行为）。
- **回落 WARN 观察钩子（两层留痕）**：fenixd 侧，回落形态生效时发一条 `WARNING` 留痕，文案含「未分配 provider 链，回落 harness 默认配置」语义与角色名，每 daemon 进程每 adapter 至多一次（进程级去重，不做持久化——daemon 重启后再提醒一次属可接受的观察成本）；MUST NOT 拒绝 spawn，claude 与 dsh 两 adapter 各自独立去重。Bundle 侧为独立观测面：`config.model` 缺席的回落启动在 dsh 侧日志留痕一条回落 WARN（含「config.model 缺席，回落 dsh 默认档」语义），显式链启动（patch 在场）不产生该 WARN——启动诊断一眼可辨回落形态与显式链形态。
- **归因降级标记**：回落 run 的 run metrics 上下文附 `provider_source: "harness-default"`，provider/model 维持既有 null/钉死形态；读侧无此键即显式链 run。回落判定信号 = 该 Agent 无 provider 链分配（`_get_agent_model_assignment` 返回空），与 adapter 内三要素全空判定同源，禁另立口径。计费、健康检查等消费侧据此区分显式链 run 与回落 run。

## 关键行为

无分配 spawn 请求 → adapter 检测 env 链键全空 → claude 按环境继承/CLI 默认档组装、dsh 组装无 `--patch` 的 argv → 进程级一次性 WARN → run metrics 落 `provider_source: "harness-default"`。dsh profile 默认模型不可用时走既有失败轨（transient/熔断），失败证据含 dsh stderr，不新增静默面。bundle 侧无 patch 启动 → modelConfig 判定回落形态 → dsh-base 默认档供数 + 插件 WARN → `headless-runner` 激活、进程执行任务。

## 代码锚点

- 单源符号：`dsh-bundle/src/modelConfig.ts`（config.model 形态划界：整体缺席回落 / 部分配置 fail-fast）
- 消费方：`core/agent_runner/harness/dsh_adapter.py`（无 patch spawn 装配与 `build_env` 桥接划界）
- 守卫测试：`tests/test_harness_default_fallback.py`（对称回落回归、一次性 WARN 去重、显式链字节级不变）、`dsh-bundle/tests/modelConfig.test.ts`（形态划界三向：回落/部分 fail-fast/显式链恒等）

## 溯源

- 2026-11-03 add-harness-default-key-fallback（spec/changes/add-harness-default-key-fallback/） — 新增本能力：无分配对称回落（dsh 省略 `--patch`/claude 环境继承）、回落与部分链笔误防护划界（env 链键存在性判定、`req.model` 不参与）、进程×adapter 一次性 WARN 钩子、`provider_source` 归因降级标记；「绝不回退 dsh 默认档」旧纪律被本能力取代
- 2026-11-08 add-dispatch-precheck-true-fallback（spec/changes/add-dispatch-precheck-true-fallback/） — bundle 侧兑现对称回落：modelConfig 形态划界（`config.model` 整体缺席=回落交 dsh-base 默认档供数、null/空串/缺要素仍 fail-fast）、bundle 回落 WARN 独立观测面、显式链校验路径回归红线——dsh 形态回落由此实际可达（此前 bundle 无条件断言 `config.model` 在场使声明的 dsh 回落不可达）
