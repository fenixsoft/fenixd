## Why

daemon 的代码陈旧检测（`improve-hot-reload-robustness` D4）已于 2026-09-05 落地，且**足够灵敏**——09-12 事故中它在消费逻辑提交后 2.5 分钟就准确命中。但它的输出止步于**一行 WARNING 日志**：既不在 dashboard 可见，也不触发任何动作，且因 `_CODE_STALE_WARNED` 模块级旗标每进程只提示一次，之后永久静默。

结果是：在自我开发场景下（agent 持续修改 `/root/fenixd` 自身代码），daemon 长期运行旧代码而无人知晓。主树当下即是活实例——`core/pm_engine/verification.py` 的 mtime 已晚于 daemon 启动时刻，今日 09:27 命中并写过 WARNING，此后无任何动作，`restart_request` 也不存在。

同时，**空闲重启的能力早已存在**（`.fenix/hooks/restart-daemon-when-idle.py`，含双轮空闲确认、防重入、超时放弃、fail-safe），但它有两个结构性缺陷：① 触发源绑死在单个 SPEC（`hooks.specs.add-judge-artifact-gate`）的 `done` 事件上，不是通用机制；② 它跑在 hook 里，看不到 daemon 内部的 `_active_runs`，只能靠 `ps` 轮询猜测活跃 run。

现在修的理由：本项目是自我开发的，daemon 陈旧是**常态而非异常**。把「检测」接到「自愈」上，"改代码 → 空闲 → 新代码生效"才形成闭环；否则每次代码落地都要靠人记得去看日志再手动重启。

## What Changes

- 陈旧检测从「一次性 WARNING」升级为「**持续状态 + escalation 告警**」：每个检测周期重算，命中时写 `signal_type: stale_code` 告警（未处置去重），重启后自然解除。
- daemon 主循环内建**空闲感知自愈**：陈旧 + 配置启用 + 项目受 supervisor 托管 + 连续空闲达阈值 → `touch .fenix/restart_request`（复用既有 supervisor 协议，**不改协议本身**）。
- 明确「空闲」判定：`agent_runner` 无活跃 run（`_active_runs == 0`）**且** admin 处置 worker 池无在途任务；任一非零即清零计时。
- 项目托管态为 `unmanaged` 时**不自愈**（无 supervisor 则信号无人消费），维持告警，交由 `fix-supervisor-hosting-chain` 的安装托管路径处置。
- 新增配置节 `stale_code_selfheal`（`enabled` 默认 `true`、`idle_confirm_seconds` 默认 `120`），并新增 Dashboard 设置页界面（遵循「新增配置项必须带界面」的既有约束）。
- `bin/fenixd_supervisor.py` 新增**启动失败熔断**：daemon 启动后短时间内连续崩溃达阈值时，停止自动拉起并落 critical 告警，避免坏代码把「可恢复的陈旧」变成「永远起不来」。
- **删除** `.fenix/hooks/restart-daemon-when-idle.py` 与 `config.yaml` 中挂载它的 hook 项——职责被 daemon 内建替代后，保留它意味着「空闲重启」有两条实现路径。

## Capabilities

### New Capabilities

- `stale-code-selfheal`: daemon 代码陈旧的持续状态与可观测性、空闲感知自愈触发（触发条件、空闲判定、托管前置、边界）、`stale_code_selfheal` 配置与界面契约、supervisor 的启动失败熔断。

### Modified Capabilities

（无——本次不改变任何既有 capability 的 requirement 语义。陈旧检测的既有纯函数与 `restart_request` 协议均按原样复用；`supervisor_running`/`hosting_state` 由前置 SPEC `fix-supervisor-hosting-chain` 引入，本 SPEC 声明依赖而非重复定义。）

## Impact

- **代码**：`fenixd.py`（陈旧持续状态 + 告警 + 主循环自愈触发）、`bin/fenixd_supervisor.py`（启动失败熔断）、`core/config.py`（新配置节读取）、`core/dashboard/server.py`（配置读写暴露）、Dashboard 前端（`settings/index.tsx` 挂载新面板 + 新建 `settings/components/StaleCodeSelfhealPanel.tsx` + `services/dashboard.ts` 类型扩展）。
- **配置**：新增 `stale_code_selfheal` 节，默认值即启用；走既有 30s 配置热更新，改配置立即生效。
- **删除**：`.fenix/hooks/restart-daemon-when-idle.py`（运行时文件，非 git 交付物）与 `config.yaml` 中 `hooks.specs.add-judge-artifact-gate` 的 `restart-daemon-when-idle` hook 项。
- **文档**：`docs/help/09-config.md`（新配置节）、`docs/help/07-safeguards.md`（自愈与熔断语义）、`docs/help/08-dashboard.md`（设置页界面）。
- **依赖（不修改）**：`core/fenix_session.py` 的 `supervisor_running()` / `hosting_state()` 由前置 SPEC `fix-supervisor-hosting-chain` 交付，本 SPEC 只调用不定义；经 STATE.md `depends_on` 排队。
- **风险**：自动重启会把新代码引入运行中的系统——若新代码无法启动则形成拉起失败循环。由本 SPEC 的熔断机制缓解；配置开关提供人工关闭通道。
- **非目标**：不改 `restart_request` 文件信号协议；不改 daemon 排水/恢复语义；不做 supervisor 自身自动升级（`fix-supervisor-hosting-chain` D7 已定论）；不做审批推送的前端消费确认（信号滞留反馈属独立议题）。
