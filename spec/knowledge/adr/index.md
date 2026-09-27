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
| [ADR-018](ADR-018-push-main-first-sha-idempotent.md) | accepted | pushed 终态以远端内容（SHA）为准：main 先行为成功判据、分支仅审计留痕，ls-remote 去重幂等、失败有界退避超限升级人工 |
| [ADR-019](ADR-019-repair-channel-dedup-family-cap.md) | accepted | 同根缺陷双修复通道（重实现/派生子 fix）先到先得，重置/spawn/派发三边界守卫互斥；族谱深度宽度硬上限越界转人工 |
| [ADR-020](ADR-020-provider-4xx-circuit-breaker.md) | accepted | provider 4xx 熔断：判据只认解析出的状态码、状态进程内存不落盘，熔断期不动状态机不增重试计数 |
| [ADR-021](ADR-021-mergeback-conflict-selfheal-keep-merge-result.md) | accepted | merge-back 冲突自愈保 merge 结果：pop 冲突 checkout HEAD 弃 stash 版本、untracked 按分支新增路径交集移开备份，不一致副本不静默丢弃 |
| [ADR-022](ADR-022-watchdog-thresholds-derived-single-source.md) | accepted | 看门狗阈值单源派生：恢复阈值=run_timeout+固定宽限，成对时间阈值一律派生自锚点旋钮不设独立键，绝对上限联动校验 |
| [ADR-023](ADR-023-worktree-isolation-cwd-seeding-mergeback.md) | accepted | 实现车道 worktree 隔离三要素：子进程 cwd 锚定 worktree（写读同层）、SPEC 播种分支自包含、成功后框架 merge-back 回主树 |
| [ADR-024](ADR-024-agent-dispatch-thread-per-run.md) | accepted | agent 派发线程化：每运行一 worker 线程、派发即返不阻塞事件循环，max_concurrent 以计数守卫落实 |
| [ADR-025](ADR-025-run-timeout-liveness-supervision.md) | accepted | 运行时限活性监督：零事件直判停滞、有活动才问 LLM（复用 fallback 路由），续期同步顺延 stuck 基准，锁与存活唯一真相是进程表 |
| [ADR-026](ADR-026-resume-via-progress-injection-not-environment.md) | accepted | 断点续跑以进度数据注入实现，跨 attempt 不复用运行环境；与 attempt 内 --resume 续跑分属不同机制 |
| [ADR-027](ADR-027-verify-failure-deterministic-triage.md) | accepted | 验证失败分流用确定性规则：环境性失联探针后置分类、噪音/缺陷按「断言从未执行」分流，不进 prompt 不用 LLM，噪音走告警不自动改场景 |
| [ADR-028](ADR-028-verify-report-synthesis-fallback.md) | accepted | 人读验证报告缺失时由结构化数据确定性合成兜底：agent 报告优先、兜底不覆盖不静默（必发告警）、合成器单一共享实现 |
| [ADR-029](ADR-029-spec-toolchain-native-selfcontained.md) | accepted | SPEC 工具链原生自包含：原生 Python 重实现移除 npm CLI，schema vendored 随库分发，changes 目录布局契约不变 |
| [ADR-030](ADR-030-dashboard-control-plane-file-signals.md) | accepted | dashboard 控制面以文件信号驱动 daemon：server 不直接派发 agent，请求落盘由 daemon 轮询拾取，信号文件即互斥且崩溃安全 |
| [ADR-031](ADR-031-dashboard-project-lifecycle-tmux-softdelete.md) | accepted | 项目运维：daemon 启停走 tmux 会话（优雅信号优先、kill 兜底、启动幂等），软删除=ignored 忽略列表（忽略优先于显式注册） |
| [ADR-032](ADR-032-failover-chain-element-model-mapping.md) | accepted | failover 链元素级模型映射：元素 str|{provider,model} 三级解析回退、角色级 model 可选，校验改「每元素可解析」，保存整体替换防覆写 |
| [ADR-033](ADR-033-v2-frontend-vendored-amis-sdk.md) | accepted | v2 前端栈=vendored AMIS SDK+JSON DSL 页面：tarball 提取无构建链、页面 JSON 深合并单页缺失可跳过；修订 ADR-008 前端形态，其零构建/vendored 原则延续 |
