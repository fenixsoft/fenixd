# ADR-313：harness 对称无分配回落与部分链笔误防护划界

date: 2026-11-03
status: accepted

## Context

回落语义在两 harness 间不对称：claude 形态靠环境继承天然开箱可用，dsh 形态却在适配器三要素预检处 fail-fast（实证 2026-11-02 dsh-plugins arbiter run 0.001s/0 tokens 秒败）。原「绝不回退 dsh 默认档」纪律（源于 10-09 CLI 默认档别名拒识事故与 provider 归因诉求）与用户 2026-11-03「开箱即用」裁定冲突；且该纪律的两条理由（别名拒识风险、归因弱化）对 claude 回落同样成立——单独豁免 dsh 无依据。

## Decision

1. 回落合法化且 harness 对称：`SpawnRequest` 无 provider 链分配即按 harness 自身配置启动（claude=环境继承/CLI 默认档；dsh=省略 `--patch` 按 profile 默认档），禁以预检错误拒绝 spawn；后续新增 harness adapter 同受此契约约束。
2. 回落与配置错误的划界以 `env_overrides` 的 provider 链键存在性为准：完全无链键 = 合法回落；含任一链键但三要素不全 = 配置笔误仍报 `DshSpawnConfigError`；`req.model` 不参与回落判定（无分配车道传钉死模型名仍是回落形态）。
3. 回落可观测走「一次性 WARN + 归因降级新键」：WARNING 每进程每 adapter 至多一次（进程级去重，不做持久化）；run metrics 上下文新键 `provider_source: "harness-default"` 表达降级归因，禁重载既有 provider/model 键的语义。
4. dsh 回落通道以「省略 `--patch`」承载，禁写空 patch 表达回落——「无 patch = profile 默认档」是 profile 系统原生语义，空 patch 引入空值渲染歧义。

## Consequences

「绝不回退默认档」纪律整体废弃；网关别名拒识风险不再用 fail-fast 防御，改由 WARN 观察与 `provider_source` 标记兜底（计费/健康检查消费侧可识别回落 run）。dsh profile 默认模型不可用时走既有失败轨（transient/熔断），失败证据含 dsh stderr，不新增静默面。显式全链 spawn 产物逐字节恒定为回归红线；任何要恢复「无分配即报错」或重载既有归因键的提案须显式 supersede 本裁定。
