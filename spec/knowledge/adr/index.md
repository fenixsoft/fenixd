# ADR 索引

跨 SPEC 架构级决策记录。每行一条：编号链接、状态、一句话摘要；
superseded 条目保留在列供溯源。编号接续本目录既有最大号。

| 编号 | 状态 | 摘要 |
| --- | --- | --- |
| [ADR-001](ADR-001-agent-run-jsonl-protocol.md) | accepted | Agent 运行产物以 stream-json 逐行落盘 `.fenix/runs/<run_id>.jsonl`，终态行协议保证文件任何时刻可解析 |
| [ADR-002](ADR-002-model-routing-env-plus-official-model.md) | accepted | 模型路由：进程 env 承载真实 baseurl/key/model，`--model` 恒取官方名（`sdk_model`）只过 SDK 校验 |
| [ADR-003](ADR-003-agent-lane-claude-config-dir-isolation.md) | accepted | 配置了 provider 的 agent 车道必须以 `CLAUDE_CONFIG_DIR` 隔离启动，凭据走进程 env 不落盘 |
| [ADR-004](ADR-004-provider-failover-attempt-boundary.md) | accepted | provider 候选链的失效转移只在 attempt 边界推进，切换类错误驱动、4xx 维持熔断、跨 provider resume 零损上下文 |
| [ADR-005](ADR-005-strict-priority-tiered-parallel-scheduling.md) | accepted | 调度为严格优先级分档并行：同档并行至 `max_concurrent`，跨档不并行、不抢占 |
| [ADR-006](ADR-006-config-tiered-deep-merge.md) | accepted | 配置分级：用户级 `~/.fenix/config.yaml` 与项目级深度合并，项目级优先、list 整体替换、缺省键兜底 |
| [ADR-007](ADR-007-multi-project-discovery.md) | accepted | 多项目发现 = 显式注册 + 目录扫描兜底（未配置扫 `~` 一级），项目识别判据仅 `STATE.md` |
| [ADR-008](ADR-008-dashboard-zero-dependency-stack.md) | accepted | Dashboard 固定零新增依赖栈：stdlib http.server + 无构建原生前端 + vendored marked |
| [ADR-009](ADR-009-dashboard-file-endpoint-security-model.md) | accepted | Dashboard 文件读取端点统一安全模型：白名单 + kebab 校验 + resolve 后目录前缀校验，缺失返回 `found:false` |
| [ADR-010](ADR-010-dashboard-writes-via-state-machine.md) | accepted | Dashboard 对状态/配置的写回一律复用既有写入口（flock 序列化 + 原子 rename），并发为最后写者胜 |
| [ADR-011](ADR-011-auto-approve-driven-by-daemon.md) | accepted | auto 审批模式由 daemon 在 done 后执行 push 并标记 pushed；默认 manual，失败保留 done 人工兜底 |
| [ADR-012](ADR-012-admin-zero-llm-monitor-and-main-tree.md) | accepted | 自愈监视零 LLM 成本（规则检测），仅困境时唤起 Administrator；其处置直接落 main 树 |
| [ADR-013](ADR-013-task-writeback-and-completion-gate-at-transitions.md) | accepted | 任务进度回写（只增不减）与完成度门禁挂在 pm_engine 的 run 终态/状态转换点，不在 agent_runner |
| [ADR-014](ADR-014-unattended-retry-safety.md) | accepted | 无人值守重试安全：错误指纹熔断、主树脏走 stash 不 commit、daemon 单实例 flock、max_turns/续跑/孤儿清理 |
| [ADR-015](ADR-015-graceful-shutdown-drain-and-interrupted-mark.md) | accepted | 优雅退出秒级排水（SIGTERM 全部→interrupted 标记→≤10s→SIGKILL），不扩展 supervisor 窗口 |
| [ADR-016](ADR-016-dispatch-selfheal-discipline.md) | accepted | 调度自愈纪律：状态机纯记录直调补发、重发幂等不清历史字段、孤儿判定白名单、单条异常不中止整轮 |
| [ADR-017](ADR-017-fake-success-defense-fail-closed-promotion.md) | accepted | 假成功防御：rc==0 须校验 result 终态；晋级关 fail-closed、推送关 fail-open；VERIFIED→TESTING 仅限自动回退 |
