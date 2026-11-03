# harness 默认档对称回落

<!-- knowledge: capability=harness-default-fallback rev=1
     sources=spec/changes/add-harness-default-key-fallback -->

无 `agents.models` 分配的 Agent 按 harness 自身配置开箱启动的对称回落契约：回落合法、笔误仍拦截、回落可观测（一次性 WARN + metrics 归因标记），claude 与 dsh 两通道语义对齐。

## 规则

- **对称回落语义**：`SpawnRequest` 无 provider 链分配时，车道按各 harness 自身配置启动，MUST NOT 以预检错误拒绝 spawn——claude 适配器走环境继承 + CLI 默认档；dsh 适配器省略 `--patch`（不写 patch 文件、argv 不携带该参数），由 dsh 按 profile 自身配置的默认模型启动，`build_env` 不桥接 `FENIX_DSH_PROVIDER_API_KEY`。dsh 侧「无 patch = profile 默认档」是回落通道的原生语义，禁以写空 patch 表达回落。
- **回落与配置笔误的划界**：回落判定以 `env_overrides` 的 provider 链键存在性为准——完全无链键（baseurl/apikey 均空）即回落形态；含任一链键但三要素不全（仅 baseurl、仅 apikey、baseurl+apikey 缺 model）属配置笔误，仍 MUST 抛 `DshSpawnConfigError`。`req.model` 不参与回落判定（无分配车道传钉死模型名仍是回落形态）；链键值为空白串视为空；非链的自定义 env_overrides 照常透传。
- **显式链形态不受回落语义改写**：显式全链 spawn 产物为 argv 含 `--patch` 且 patch 文件落盘渲染 model/baseURL 三要素、env 桥接 `FENIX_DSH_PROVIDER_API_KEY`、`ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY` 两 consumed 键不透传子进程——该形态逐字节恒定，是回落语义的回归红线。
- **回落 WARN 观察钩子（一次性）**：回落形态生效时发一条 `WARNING` 留痕，文案含「未分配 provider 链，回落 harness 默认配置」语义与角色名；每 daemon 进程每 adapter 至多一次（进程级去重，不做持久化——daemon 重启后再提醒一次属可接受的观察成本）；MUST NOT 拒绝 spawn。claude 与 dsh 两 adapter 各自独立去重。
- **归因降级标记**：回落 run 的 run metrics 上下文附 `provider_source: "harness-default"`，provider/model 维持既有 null/钉死形态；读侧无此键即显式链 run。回落判定信号 = 该 Agent 无 provider 链分配（`_get_agent_model_assignment` 返回空），与 adapter 内三要素全空判定同源，禁另立口径。计费、健康检查等消费侧据此区分显式链 run 与回落 run。

## 关键行为

无分配 spawn 请求 → adapter 检测 env 链键全空 → claude 按环境继承/CLI 默认档组装、dsh 组装无 `--patch` 的 argv → 进程级一次性 WARN → run metrics 落 `provider_source: "harness-default"`。dsh profile 默认模型不可用时走既有失败轨（transient/熔断），失败证据含 dsh stderr，不新增静默面。

## 溯源

- 2026-11-03 add-harness-default-key-fallback（spec/changes/add-harness-default-key-fallback/） — 新增本能力：无分配对称回落（dsh 省略 `--patch`/claude 环境继承）、回落与部分链笔误防护划界（env 链键存在性判定、`req.model` 不参与）、进程×adapter 一次性 WARN 钩子、`provider_source` 归因降级标记；「绝不回退 dsh 默认档」旧纪律被本能力取代
