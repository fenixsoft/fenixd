## Context

cloud-phone 新项目首跑（2026-11-08）完整暴露派发链路三处断点，故障链有日志实证（`.fenix/logs/fenixd.log` 07:52–08:49 UTC）：

1. **bundle 侧回落断桥**：`harness-default-fallback` 能力（2026-11-03）在 fenixd 侧实现了对称回落（无分配 → 省略 `--patch`），但 dsh-bundle `src/modelConfig.ts` 的 `assertModelExplicit` 在插件创建期无条件要求 `config.model`（L48-70，「绝不回退 dsh 默认档」为承袭网关别名事故的旧纪律 D9 残留）。无 patch 时 `config.model` 为 undefined → StartupError → required 插件 `headless-runner` 无法激活（诊断日志：`missing: ['agentDefaultModel', 'fenixModelConfig']`）→ 秒挂 3 次。知识页声称「模型显式配置契约收窄为 patch 渲染路径」与实现不符。
2. **CLI 不可达无归因**：systemd 托管 daemon 进程 PATH 为最小系统集（`/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`），`claude` 实际安装于 `/root/.local/bin/claude` → 所有派发 `[Errno 2] No such file or directory: 'claude'`，报错不指向任何可行动作，且计入通用失败循环。
3. **env 捕获自吞噬**：`bin/migrate_to_systemd.py:403` 从「迁移时刻在跑进程」捕获 env。老项目在 shell 时代迁移（捕获完整 PATH）；新项目出生即 systemd 托管，唯一捕获源就是 systemd 拉起的最小 PATH supervisor → 坏 PATH 落盘 `systemd.env` → unit（`EnvironmentFile=-`）每次重启加载 → 循环封闭；幂等重跑（L406「正式 env 在场 → 跳过捕获」）进一步固化。

用户裁定（2026-11-08）：dsh+fenix 走**真对称回落**。

## Goals

- 无 `agents.models` 分配时 dsh+fenix 与 claude 语义对称：都以 harness 自身配置开箱启动
- harness CLI 不可达从「裸 FileNotFoundError + 通用失败循环」变为「显式归因 + actionable 告警 + 可自愈」
- 新项目 systemd 托管从第一天起 PATH 完整，坏 PATH 不再被捕获固化

## Non-Goals

- 不改变显式链 spawn 语义（字节级回归红线）
- 不在本 SPEC 内执行 cloud-phone 等存量项目的修复（落地后由自愈链路 + 运营动作完成）
- 不引入新配置键（基线目录集为模块常量，不做 per-project 配置）

## Decisions

### D1 bundle 侧回落：按形态划界，缺席回落、部分缺失 fail-fast

`assertModelExplicit` 改为两分支：
- **`config.model` 整体缺席（undefined / 无 patch 形态）**：不抛错。插件跳过显式覆盖，`agentDefaultModel`/`fenixModelConfig` 服务交由 dsh 自身默认模型解析链（dsh-base 通道，web profile 同源）供数，并以插件日志 WARN 留痕（含「config.model 缺席，回落 dsh 默认档」语义）。判定基准是「键整体缺席」而非「值为空」——`config.model: null` 与空串属部分配置，走 fail-fast。
- **`config.model` 在场但任一要素缺失/为空**：保持现行 fail-fast（笔误防护，D2 语义不变）。

回落形态下 `headless-runner`（required）必须正常激活——这是「真对称回落」的验收锚点：无分配 spawn 进程存活并执行任务。fenixd 侧 `warn_harness_default_fallback`（进程×adapter 一次性）与 `provider_source: "harness-default"` 归因标记不变；bundle 侧 WARN 为独立观测面，两层留痕语义互补。

### D2 归因标记 `[harness-cli-unavailable]` 与升级信号豁免

派发前置自检（`shutil.which`）不可达时短路该次派发（不产生 spawn 进程），失败证据带 `[harness-cli-unavailable]` 标记（与既有 `[model-chain-unavailable]` 同层同形，归因管道复用 `core/agent_runner/runner.py` 既有标记位）。该类失败不计入 instant-fail-storm / repeated-failures 计数——这两组信号按「模型链语义」设计升级路径，CLI 缺失归因不同（重试无意义，修复环境才有意义），升级路径改为单条 actionable 告警 + 进程内去重。

### D3 PATH 卫生：基线并集追加，不动 systemd 加载顺序

- 基线目录集为模块常量（`~/.local/bin`、`/usr/local/bin`、`/usr/local/sbin`、`/usr/bin`、`/bin`、`/usr/sbin`、`/sbin`），追加到捕获源 PATH **尾部**（尾部目录仅为回退语义，不改变既有目录优先级，无越权覆盖风险）。
- unit 模板保底 `Environment=PATH=` 仅在 env 文件缺席时生效（systemd 语义：EnvironmentFile 覆盖 unit Environment=），不与 env 文件竞争。
- daemon 启动自愈：`~/.local/bin/<harness>` 存在而 PATH 缺该目录 → 追加写入 `.fenix/systemd.env` PATH 行（幂等）+ 落 `restart_request`（复用既有 supervisor 消费链，参照 fix-dashboard-read-path-performance 任务 6.2 的「信号落位 + 预演」范式）。binary 全目录未找到时不盲写 env，只发告警。

### D4 迁移摘要可见性

`migrate_to_systemd.py` plan 摘要追加一行 PATH 卫生结论（「完整」或「补齐 <目录清单>」），人工审核环节一眼可判。

## Risks

- **bundle 回落模型与显式链模型能力差异**：回落 run 的计费/健康检查读侧已有 `provider_source: "harness-default"` 标记区分，消费侧语义闭环；bundle 侧不做计价。
- **dsh 版本演进改变 dsh-base 默认模型解析**：bundle 单测以 mock 注入隔离 dsh-base 依赖；真机探针（无 patch 启动 + headless 端到端）列为实现收尾冒烟项。
- **worktree 内 bundle 构建**：dsh-bundle/node_modules 为 gitignored，worktree 首次需 `pnpm install`（既有先例 add-fenix-dsh-bundle 已验证可行；workspace 用 link: 协议）。
- **自愈写 env 文件的并发安全**：`.fenix/systemd.env` 为 0600 运行时文件，追加操作走原子写（tmp+rename，与 `write_env_file` 同款）。

## Migration Plan

- 新项目：捕获卫生 + unit 保底即时生效，无迁移
- 存量坏 PATH 项目（cloud-phone）：daemon 升级重启后启动自检发现 → 自愈补目录 + restart_request → 重启后自检通过
- fenixd 自身：PATH 已完整，自检通过态零动作

## Revert Plan

bundle 侧行为由 `assertModelExplicit` 单点承载，revert 即恢复 fail-fast；自检/归因/卫生均为增量路径，revert 无残留状态（env 文件已追加的目录保留无害）。
