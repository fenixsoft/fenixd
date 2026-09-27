<!-- knowledge: capability=parallelism-config rev=1 sources=spec/archive/2026-09-02-add-parallelism -->

# 并行度配置

`agents.max_concurrent` 的并行度语义、校验与 Dashboard 可视化编辑：决定同一时刻最多运行多少个 Agent 进程。

## 现行规则

- `agents.max_concurrent` 语义为「并行度」：同一时刻允许运行的 Agent 进程数上限（同优先级任务可并行至该值）。
- 配置经 `ConfigLoader` 加载并校验：须为正整数，非正数或非整数导致配置校验失败并抛出说明字段的配置错误。
- 可选字段：键不强制存在，未显式配置时使用代码缺省值（当前缺省值口径见 [派发并发度调优](dispatch-concurrency-tuning.md)，两页单源同键）。
- Dashboard 配置页提供并行度的数字输入与保存：复用 `POST /api/config` 将新值写回 `.fenix/config.yaml` 的 `agents.max_concurrent`，并保留 `agents` 下其它子键（如 `subagent_model`、`max_retries`、`max_turns`）及 `llm`、`gates` 等其它受管键原值不变。
- 提交非法并行度（非正整数）返回 400 与错误说明，配置文件内容不变。
- 保存后经配置热更新生效（约 30 秒内），无需重启 daemon。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：max_concurrent 并行度经 Dashboard 配置并热更新生效；可选字段不强制存在
- 2026-09-02 2026-09-02-add-parallelism — 明确 `agents.max_concurrent` 的并行度语义、正整数校验与模板注释说明；Dashboard 配置页接入可视化编辑（复用 GET/POST /api/config，保存保留其余子键、非法值 400 不写盘）。
