## Context

验收 `add-dashboard-paging-and-etag` 时发现「SPEC 合入 ≠ dashboard 生效」：dashboard 是独立 tmux 进程（`fenix-dashboard` 会话），不在 supervisor 托管链内，`restart_request` 信号只覆盖 daemon。HookEngine 七动作中的 `restart-dashboard`（`tmux respawn-window -k` + 固化命令 + 端口可服务判据）已完整实现但从未被自动触发——config 中 `hooks` 段只有一条历史 webhook。

约束：
- `match_hooks` 的 global 作用域对任意 SPEC 匹配（`hook_engine.py:299`），无需通配机制。
- `.fenix/config.yaml` 是 gitignored 运行时文件，worktree 内实现 agent 不可达（主树只读 + worktree 无 gitignored 文件）——**纯配置方案不可交付**，默认行为必须进代码。
- HookEngine.dispatch 已保证异常不向状态机传播；动作失败只记审计。
- 新增配置键必须带 Dashboard 界面（用户规则）。

## Goals / Non-Goals

**Goals**
- pushed 后 dashboard 自动加载最新代码，消灭「合入后跑旧代码」盲态。
- push 批次不产生重启风暴；无 dashboard 环境不产告警噪音。

**Non-Goals**
- **daemon 不挂自动重启**：pushed 时可能有其它 SPEC 的在飞 run，daemon 重启会打断在飞批（排水终止→chain_skipped，见 restart_request 中断实测）——daemon 重启维持既有 supervisor/人工链路。
- 不做跨进程去抖持久化（进程内时间戳足够：daemon 重启后首个 pushed 多重启一次，无害）。
- 不改 restart_request / supervisor 协议。

## Decisions

### D1. 默认行为进代码：`hook_config()` 注入内置条目

`hook_config()` 在返回前向 global 段头部注入 `{"id": "builtin-push-restart-dashboard", "enabled": True, "events": ["pushed"], "action": "restart-dashboard"}`（读侧注入，不改 config 文件）。逃生键 `hooks.push_restart_dashboard: false` 时跳过注入。选注入而非用户配置：`.fenix/config.yaml` 不可作为交付物（gitignored），且「新项目零配置即生效」符合开箱即用。

*放弃的替代*：config.yaml 挂人工步骤——违背本 SPEC「消灭人工重启」的目标。

### D2. 去抖在动作层，前沿语义

`_action_restart_dashboard` 入口检查进程内 `_last_restart_monotonic`：60s 内且上次成功 → 返回 skipped（审计留痕）。放动作层而非匹配层：所有触发路径（含未来其它动作调用）统一防抖；失败不写时间戳，窗口内可重试。60s 取值：dashboard 重启+端口就绪 ~3-5s，push 批次峰值（同日 6 个入库提交）窗口足够。

### D3. 无会话从 failure 改静默跳过

会话不存在是**环境态**而非操作失败（CI/容器本来就无 dashboard），保持 failure 会每次 pushed 产审计噪音并可能升级人工告警（违背降噪决策）。改为返回 skipped 语义 + 日志 debug。会话存在但 respawn 失败仍记 failure（那是真故障）。

### D4. 逃生键走既有 config 三链路

`hooks.push_restart_dashboard`（bool 缺省 true）经 `hook_config()` 消费；设置页 HooksPanel 加开关（MiscSettingsPanel 同款 checkbox 模式）；`/api/config` GET/POST 自然透传（config 键为宽松 schema，无后端白名单处则无需注册——实现时以既有 bool 键为先例对齐校验位置）。

## Risks / Trade-offs

- **[重启瞬间 SSE 断连]** 浏览器 EventSource 自动重连（既有兜底），用户感知 ≤5s 闪断——push 是低频事件，可接受。
- **[去抖窗口内代码更新丢失]** 60s 窗口内第二次 push 的代码要等下次 pushed 才生效——窗口极短且 push 批次尾部总有收尾事件，可接受。
- **[内置条目与用户同 id 冲突]** 用户手写同 id 条目会被注入重复——注入前按 id 去重（用户条目优先）。

## Migration Plan

单 commit 交付：代码注入默认行为 + 去抖/静默 + 设置页开关 + 测试。无数据迁移，config 热更新（30s mtime）自然加载新键。

## Open Questions

（无）
